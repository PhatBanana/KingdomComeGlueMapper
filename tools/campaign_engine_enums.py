"""Read literal engine enum serializers from the user's installed KCD1 DLL.

This is read-only metadata extraction, not an engine patch. Only the observed
x64 XML enum serializer contract is accepted. Names, ordinals, instruction
addresses and the binary hash are retained; nearby strings are never treated
as an enum declaration and ordinal sequences are never inferred.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct


def decode_serializer(events):
    """Recognize ordered constant XML emission from one complete function.

    Events contain only verified RIP string loads and immediate r8d values.
    The disassembler rejects functions with conditional/unconditional jumps,
    so no branch-dependent member values can be flattened into a declaration.
    """
    if len(events) < 3 or events[0].get('text') != 'enum':
        raise ValueError('Not a literal XML enum serializer')
    if (events[0]['register'] != 'r8' or events[1]['register'] != 'r8'
            or events[2].get('text') != 'name' or events[2]['register'] != 'rdx'):
        raise ValueError('Unsupported engine enum declaration header')
    name = events[1].get('text', '')
    if not re.fullmatch(r'[A-Za-z_]\w*', name):
        raise ValueError('Invalid engine enum name')
    values, position = [], 3
    while position < len(events):
        chunk = events[position:position + 4]
        if (len(chunk) != 4 or chunk[0].get('text') != 'Member' or chunk[0]['register'] != 'r8'
                or chunk[1]['register'] != 'rdx' or chunk[2].get('text') != 'value'
                or chunk[2]['register'] != 'rdx' or chunk[3]['register'] != 'r8d'
                or 'integer' not in chunk[3]):
            raise ValueError('Unsupported engine enum member serializer')
        member = chunk[1].get('text', '')
        if not re.fullmatch(r'[A-Za-z_]\w*', member):
            raise ValueError('Invalid engine enum member')
        if not 0 <= chunk[3]['integer'] <= 0x7fffffff:
            raise ValueError('Signed engine enum ordinal ABI needs explicit evidence')
        values.append(dict(name=member, ordinal=chunk[3]['integer'],
            name_rva=chunk[1]['rva'], value_rva=chunk[3]['rva']))
        position += 4
    if not values or len({value['name'] for value in values}) != len(values):
        raise ValueError('Missing or duplicate engine enum members')
    return dict(name=name, values=values)


def extract_engine_enums(binary, names):
    # These are local inspection dependencies, imported only for this tool.
    # The distributable importer can consume its evidence JSON independently.
    import capstone
    import pefile
    names = set(names)
    if not names or any(not re.fullmatch(r'[A-Za-z_]\w*', name) for name in names):
        raise ValueError('Explicit engine enum identities are required')
    path = Path(binary)
    data = path.read_bytes()
    pe = pefile.PE(data=data, fast_load=True)
    if pe.FILE_HEADER.Machine != 0x8664:
        raise ValueError('Only the verified x64 serializer format is supported')
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXCEPTION']])
    functions = sorted((row.struct.BeginAddress, row.struct.EndAddress)
                       for row in pe.DIRECTORY_ENTRY_EXCEPTION)
    base = pe.OPTIONAL_HEADER.ImageBase
    targets = {}
    for name in names:
        token = name.encode('ascii') + b'\0'
        for match in re.finditer(re.escape(token), data):
            targets[base + pe.get_rva_from_offset(match.start())] = name
    refs = set()
    # Resolve actual x64 RIP-relative LEA references; an adjacent member name
    # in .rdata supplies no evidence of its ordinal or enum ownership.
    for section in pe.sections:
        if not section.Characteristics & 0x20000000:
            continue
        code = section.get_data()
        for match in re.finditer(rb'[\x48\x4c]\x8d[\x05\x0d\x15\x1d\x25\x2d\x35\x3d]....', code, re.S):
            offset = match.start()
            rva = section.VirtualAddress + offset
            target = base + rva + 7 + struct.unpack_from('<i', code, offset + 3)[0]
            if target in targets:
                refs.add(rva)
    candidates = {span for span in functions if any(span[0] <= ref < span[1] for ref in refs)}
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    decoder.detail = True
    records, rejected, ambiguous = {}, [], set()
    for start, end in sorted(candidates):
        offset = pe.get_offset_from_rva(start)
        code = data[offset:offset + end - start]
        events = []
        try:
            decoded = list(decoder.disasm(code, base + start))
            if not decoded or sum(i.size for i in decoded) != len(code):
                raise ValueError('Incomplete function disassembly')
            if any(i.group(capstone.CS_GRP_JUMP) for i in decoded):
                raise ValueError('Branching serializer needs control-flow conversion')
            for instruction in decoded:
                ops = instruction.operands
                if instruction.mnemonic == 'lea' and len(ops) == 2 and ops[1].type == capstone.CS_OP_MEM and ops[1].mem.base == capstone.x86.X86_REG_RIP:
                    register = instruction.reg_name(ops[0].reg)
                    if register not in ('r8', 'rdx'):
                        continue
                    address = instruction.address + instruction.size + ops[1].mem.disp
                    location = pe.get_offset_from_rva(address - base)
                    raw = data[location:location + 256].split(b'\0', 1)[0]
                    text = raw.decode('ascii')
                    if not text or any(ord(char) < 32 for char in text):
                        raise ValueError('Nonliteral serializer argument')
                    events.append(dict(register=register, text=text, rva=instruction.address - base))
                elif ops and ops[0].type == capstone.CS_OP_REG and instruction.reg_name(ops[0].reg) == 'r8d':
                    if instruction.mnemonic == 'mov' and len(ops) == 2 and ops[1].type == capstone.CS_OP_IMM:
                        integer = ops[1].imm
                    elif instruction.mnemonic == 'xor' and len(ops) == 2 and ops[1].type == capstone.CS_OP_REG and ops[1].reg == ops[0].reg:
                        integer = 0
                    else:
                        raise ValueError('Nonconstant engine enum ordinal')
                    events.append(dict(register='r8d', integer=integer, rva=instruction.address - base))
            record = decode_serializer(events)
            if record['name'] not in names:
                continue
            if record['name'] in records or record['name'] in ambiguous:
                records.pop(record['name'], None)
                ambiguous.add(record['name'])
                raise ValueError('Ambiguous engine enum serializer: ' + record['name'])
            records[record['name']] = dict(record, function_start_rva=start, function_end_rva=end,
                function_sha256=hashlib.sha256(code).hexdigest())
        except (ValueError, UnicodeDecodeError, pefile.PEFormatError) as error:
            rejected.append(dict(function_start_rva=start, reason=str(error)))
    return dict(schema=1, source_binary=str(path.resolve()), sha256=hashlib.sha256(data).hexdigest(),
        enum_declarations=list(records.values()), unresolved=sorted(names - records.keys()),
        rejected_candidates=rejected, source_metadata_only=True, target_abi_validated=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--enum', dest='enums', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Choose a new evidence output')
    report = extract_engine_enums(args.binary, args.enums)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(enums=[r['name'] for r in report['enum_declarations']], unresolved=report['unresolved'])))
