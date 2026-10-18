"""Convert bounded Lua data programs without actor or profession special cases.

The grammar preserves source branches and expressions. Its only engine calls
are validated entity/property reads; it cannot bless arbitrary gameplay APIs.
"""
import re
from campaign_lua_contracts import tokens


class UnsupportedScript(ValueError):
    pass


class DataProgram:
    BINARY = {'or': 1, 'and': 2, '<': 3, '>': 3, '<=': 3, '>=': 3,
              '~=': 3, '==': 3, '..': 4, '+': 5, '-': 5, '*': 6, '/': 6, '%': 6, '^': 8}
    KEYWORDS = {'and', 'break', 'do', 'else', 'elseif', 'end', 'false', 'for',
                'function', 'if', 'in', 'local', 'nil', 'not', 'or', 'repeat',
                'return', 'then', 'true', 'until', 'while'}
    RESERVED = KEYWORDS | {'data', 'entity', 'EntityUtils', 'XGenAIModule', 'tostring',
                           'GetEntityScriptProperty', 'GetEntityMiscProperty'}

    def __init__(self, script, catalog):
        self.source = tokens(script)
        if self.source is None:
            raise UnsupportedScript('Invalid Lua tokens')
        self.pos, self.output, self.locals = 0, [], {}
        self.catalog = catalog

    def peek(self):
        return self.source[self.pos] if self.pos < len(self.source) else None

    def take(self, expected=None):
        value = self.peek()
        if value is None or expected is not None and value != expected:
            raise UnsupportedScript('Unexpected Lua token')
        self.pos += 1
        self.output.append(value)
        return value

    def name(self):
        value = self.peek()
        if not value or value in self.KEYWORDS or not re.fullmatch(r'[A-Za-z_]\w*', value):
            raise UnsupportedScript('Expected identifier')
        return self.take()

    def data(self):
        self.take('data'); self.take('.'); self.name()
        while self.peek() == '.':
            self.take('.'); self.name()
        return 'value'

    def expression(self, minimum=0, depth=0):
        if depth > 64:
            raise UnsupportedScript('Expression nesting exceeds conversion limit')
        token = self.peek()
        kind = 'value'
        if token in ('-', 'not'):
            self.take(); self.expression(7, depth + 1)
        elif token == '(':
            self.take(); kind = self.expression(depth=depth + 1); self.take(')')
        elif token == 'data':
            kind = self.data()
        elif token == 'entity':
            self.take(); kind = 'entity'
        elif token == 'XGenAIModule':
            self.take(); self.take('.'); function = self.name(); self.take('(')
            if function not in ('GetEntityByWUID', 'GetEntityIdByWUID'):
                raise UnsupportedScript('Unsupported entity lookup')
            self.data(); self.take(')')
            kind = 'entity' if function == 'GetEntityByWUID' else 'entity_id'
        elif token in ('GetEntityScriptProperty', 'GetEntityMiscProperty'):
            native, flag, required = {
                'GetEntityScriptProperty': ('GetScriptProperty', 'native_script_property_reader', 'entity'),
                'GetEntityMiscProperty': ('GetMiscProperty', 'native_misc_property_reader', 'entity_id'),
            }[token]
            if not self.catalog.get(flag):
                raise UnsupportedScript('Native property reader unavailable')
            self.take(); self.output[-1:] = ['EntityUtils', '.', native]
            self.take('(')
            actual = self.expression(depth=depth + 1)
            if actual != required:
                raise UnsupportedScript('Wrong property receiver type')
            self.take(',')
            prop = self.take()
            if not re.fullmatch(r'''(['"])[A-Za-z_][A-Za-z_0-9]*\1''', prop):
                raise UnsupportedScript('Dynamic property key')
            self.take(')')
        elif token == 'tostring':
            self.take(); self.take('('); self.expression(depth=depth + 1); self.take(')')
        elif token in self.locals:
            kind = self.locals[token]; self.take()
        elif token in ('true', 'false', 'nil') or token is not None and (
                re.fullmatch(r'\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', token)
                or len(token) >= 2 and token[0] in "'\"" and token[-1] == token[0]):
            self.take()
        else:
            raise UnsupportedScript('Unsupported expression')
        while self.peek() in self.BINARY and self.BINARY[self.peek()] >= minimum:
            op = self.take(); precedence = self.BINARY[op]
            self.expression(precedence if op in ('^', '..') else precedence + 1, depth + 1)
            kind = 'value'
        return kind

    def block(self, stops=(), depth=0):
        if depth > 64:
            raise UnsupportedScript('Block nesting exceeds conversion limit')
        while self.peek() is not None and self.peek() not in stops:
            token = self.peek()
            if token == ';':
                self.take(); continue
            if token == 'local':
                self.take(); name = self.name()
                if name in self.RESERVED or name in self.locals:
                    raise UnsupportedScript('Shadowed local')
                self.take('='); self.locals[name] = self.expression()
                self.output.append(';')
            elif token == 'if':
                self.take(); self.expression(); self.take('then')
                outer = dict(self.locals)
                self.block(('elseif', 'else', 'end'), depth + 1); self.locals = dict(outer)
                while self.peek() == 'elseif':
                    self.take(); self.expression(); self.take('then')
                    self.block(('elseif', 'else', 'end'), depth + 1); self.locals = dict(outer)
                if self.peek() == 'else':
                    self.take(); self.block(('end',), depth + 1); self.locals = outer
                self.take('end')
            elif token == 'return':
                self.take(); self.expression(); self.output.append(';')
                if self.peek() == ';': self.take()
                if self.peek() is not None and self.peek() not in stops:
                    raise UnsupportedScript('Statements after return')
            elif token == 'data':
                self.data(); self.take('='); self.expression(); self.output.append(';')
            else:
                # No global writes, unreviewed calls, loops, closures or local
                # reassignment which could invalidate property receiver types.
                raise UnsupportedScript('Unsupported statement')


def upgrade(script, catalog):
    """Return a whole converted program, or None; never return a partial edit."""
    try:
        parser = DataProgram(script, catalog)
        parser.block()
        return ' '.join(parser.output) if parser.output else None
    except UnsupportedScript:
        return None
