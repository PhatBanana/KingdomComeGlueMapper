"""Compare installed Lua contracts lexically without rewriting their programs."""
import re


TOKEN = re.compile(r'''(?:[A-Za-z_][A-Za-z_0-9]*|(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|\.\.\.|\.\.|==|~=|<=|>=|::|//|<<|>>|[+*/%^#=<>;:,{}()\[\].&|~-])''')
LONG = re.compile(r'\[(=*)\[')


def tokens(script):
    """Remove only lexical whitespace/comments; keep literals byte-for-byte.

    Token tuples distinguish `not ready` from `notready`, and quoted comment
    markers from actual comments. Unrecognized syntax is never normalized.
    """
    result, pos = [], 0
    while pos < len(script):
        if script[pos].isspace():
            pos += 1
            continue
        comment = script.startswith('--', pos)
        start = pos + 2 if comment else pos
        long = LONG.match(script, start)
        if long:
            close = ']' + long[1] + ']'
            end = script.find(close, long.end())
            if end < 0: return None
            end += len(close)
            if not comment: result.append(script[pos:end])
            pos = end
            continue
        if comment:
            newline = re.search(r'[\r\n]', script[start:])
            pos = len(script) if newline is None else start + newline.end()
            continue
        if script[pos] in "'\"":
            quote, end = script[pos], pos + 1
            while end < len(script):
                if script[end] == '\\':
                    end += 2
                elif script[end] == quote:
                    end += 1
                    break
                elif script[end] in '\r\n':
                    return None
                else:
                    end += 1
            else:
                return None
            if end > len(script): return None
            result.append(script[pos:end]); pos = end
            continue
        match = TOKEN.match(script, pos)
        if not match: return None
        result.append(match[0]); pos = match.end()
    return tuple(result)


def actor_constant_call(program):
    # Only a single actor method call with constant booleans/nil is shared
    # between callback fields. Programs using data/local scope stay site-bound.
    if program is None: return False
    return bool(re.fullmatch(r'entity(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*\((?:true|false|nil)?\);?', ''.join(program)))


class NativeLuaContracts:
    def __init__(self, catalog):
        self.by_site, self.actor_calls = {}, set()
        for op, fields in catalog.get('lua_contracts', {}).items():
            for field, scripts in fields.items():
                values = {p for s in scripts if (p := tokens(s)) is not None}
                self.by_site[op, field] = values
                if op == 'LuaWrapper' and field in ('onEnter', 'onExit'):
                    self.actor_calls.update(p for p in values if actor_constant_call(p))

    def accepts(self, op, field, script):
        program = tokens(script)
        if program is None: return False
        if program in self.by_site.get((op, field), set()): return True
        # ExecuteLua performs the same synchronous call at its original source
        # location. Do not turn a statement into a gate or move lifecycle calls.
        return op == 'ExecuteLua' and field == 'code' and program in self.actor_calls
