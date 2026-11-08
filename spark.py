import sys

KW = {"let", "if", "else", "while", "fn", "return", "true", "false",
      "and", "or", "not", "print"}

OPS = ["CONST", "POP", "LOAD", "STORE", "ADD", "SUB", "MUL", "DIV", "MOD",
       "NEG", "EQ", "NEQ", "LT", "GT", "LTE", "GTE", "NOT", "JUMP", "FJUMP",
       "CALL", "RET", "ARR", "IDX", "ISTORE", "LEN", "PRINT", "HALT"]
OP = {name: i for i, name in enumerate(OPS)}


def lex(src):
    toks, i, line = [], 0, 1
    while i < len(src):
        c = src[i]
        if c == "\n":
            line += 1; i += 1; continue
        if c in " \t\r":
            i += 1; continue
        if c == "-" and src[i:i+2] == "--":
            while i < len(src) and src[i] != "\n":
                i += 1
            continue
        if c.isdigit():
            j = i
            while j < len(src) and (src[j].isdigit() or src[j] == "."):
                j += 1
            toks.append(("num", float(src[i:j]), line)); i = j; continue
        if c.isalpha() or c == "_":
            j = i
            while j < len(src) and (src[j].isalnum() or src[j] == "_"):
                j += 1
            w = src[i:j]
            toks.append(("kw" if w in KW else "id", w, line)); i = j; continue
        if c == '"':
            j = i + 1
            while j < len(src) and src[j] != '"':
                j += 1
            if j >= len(src):
                raise SyntaxError("unclosed string on line %d" % line)
            toks.append(("str", src[i+1:j], line)); i = j + 1; continue
        two = src[i:i+2]
        if two in ("==", "!=", "<=", ">=", "&&", "||"):
            toks.append(("op", {"&&": "and", "||": "or"}.get(two, two), line))
            i += 2; continue
        if c in "+-*/%=<>!(){},[]":
            toks.append(("op", {"!": "not"}.get(c, c), line)); i += 1; continue
        raise SyntaxError("weird char %r on line %d" % (c, line))
    toks.append(("eof", "", line))
    return toks


class Parser:
    def __init__(self, toks):
        self.toks, self.pos = toks, 0

    def peek(self, k=0):
        return self.toks[self.pos + k]

    def eat(self, kind=None, val=None):
        t = self.toks[self.pos]
        if kind and t[0] != kind or val is not None and t[1] != val:
            raise SyntaxError(
                "wanted %s but got %r on line %d"
                % (val or kind, t[1], t[2]))
        self.pos += 1
        return t

    def program(self):
        out = []
        while self.peek()[0] != "eof":
            out.append(self.stmt())
        return out

    def stmt(self):
        t = self.peek()
        if t[0] == "kw":
            if t[1] == "let":
                self.eat()
                name = self.eat("id")[1]
                self.eat("op", "=")
                return ("let", name, self.expr())
            if t[1] == "if":
                self.eat()
                cond = self.expr()
                body = self.block()
                other = None
                if self.peek()[0] == "kw" and self.peek()[1] == "else":
                    self.eat()
                    other = self.block()
                return ("if", cond, body, other)
            if t[1] == "while":
                self.eat()
                return ("while", self.expr(), self.block())
            if t[1] == "fn":
                self.eat()
                name = self.eat("id")[1]
                self.eat("op", "(")
                params = []
                if self.peek()[1] != ")":
                    params.append(self.eat("id")[1])
                    while self.peek()[1] == ",":
                        self.eat()
                        params.append(self.eat("id")[1])
                self.eat("op", ")")
                return ("fn", name, params, self.block())
            if t[1] == "return":
                self.eat()
                return ("ret", self.expr())
            if t[1] == "print":
                self.eat()
                return ("print", self.expr())
        if (t[0] == "id" and self.peek(1)[1] == "[") or \
           (t[0] == "id" and self.peek(1)[1] == "="):
            name = self.eat("id")[1]
            if self.peek()[1] == "[":
                self.eat()
                idx = self.expr()
                self.eat("op", "]")
                self.eat("op", "=")
                return ("istore", name, idx, self.expr())
            self.eat("op", "=")
            return ("set", name, self.expr())
        return ("expr", self.expr())

    def block(self):
        self.eat("op", "{")
        out = []
        while self.peek()[1] != "}":
            out.append(self.stmt())
        self.eat()
        return out

    def expr(self):
        return self.orx()

    def orx(self):
        l = self.andx()
        while self.peek()[0] in ("op", "kw") and self.peek()[1] == "or":
            self.eat()
            l = ("or", l, self.andx())
        return l

    def andx(self):
        l = self.cmp()
        while self.peek()[0] in ("op", "kw") and self.peek()[1] == "and":
            self.eat()
            l = ("and", l, self.cmp())
        return l

    def cmp(self):
        l = self.add()
        m = {"==": "EQ", "!=": "NEQ", "<": "LT", ">": "GT",
             "<=": "LTE", ">=": "GTE"}
        while self.peek()[1] in m:
            op = m[self.eat()[1]]
            l = ("bin", op, l, self.add())
        return l

    def add(self):
        l = self.mul()
        while self.peek()[1] in ("+", "-"):
            op = "ADD" if self.eat()[1] == "+" else "SUB"
            l = ("bin", op, l, self.mul())
        return l

    def mul(self):
        l = self.unary()
        while self.peek()[1] in ("*", "/", "%"):
            op = {"*": "MUL", "/": "DIV", "%": "MOD"}[self.eat()[1]]
            l = ("bin", op, l, self.unary())
        return l

    def unary(self):
        if self.peek()[1] == "-":
            self.eat()
            return ("neg", self.unary())
        if self.peek()[1] == "not":
            self.eat()
            return ("notx", self.unary())
        return self.postfix()

    def postfix(self):
        e = self.atom()
        while True:
            if self.peek()[1] == "[":
                self.eat()
                e = ("idx", e, self.expr())
                self.eat("op", "]")
            elif self.peek()[1] == "(" and e[0] == "var":
                self.eat()
                args = []
                if self.peek()[1] != ")":
                    args.append(self.expr())
                    while self.peek()[1] == ",":
                        self.eat()
                        args.append(self.expr())
                self.eat("op", ")")
                e = ("call", e[1], args)
            else:
                break
        return e

    def atom(self):
        t = self.eat()
        if t[0] == "num":
            return ("num", t[1])
        if t[0] == "str":
            return ("str", t[1])
        if t[0] == "id":
            return ("var", t[1])
        if t[1] in ("true", "false"):
            return ("num", 1.0 if t[1] == "true" else 0.0)
        if t[1] == "(":
            e = self.expr()
            self.eat("op", ")")
            return e
        if t[1] == "[":
            items = []
            if self.peek()[1] != "]":
                items.append(self.expr())
                while self.peek()[1] == ",":
                    self.eat()
                    items.append(self.expr())
            self.eat("op", "]")
            return ("arr", items)
        raise SyntaxError("unexpected %r on line %d" % (t[1], t[2]))


class Compiler:
    def __init__(self):
        self.code = []
        self.fns = {}
        self.locals = None

    def emit(self, op, arg=None):
        self.code.append((OP[op], arg))
        return len(self.code) - 1

    def name(self, n):
        if self.locals is not None and n in self.locals:
            return ("local", self.locals[n])
        return ("global", n)

    def compile(self, stmts):
        for s in stmts:
            self.node(s)
        self.emit("HALT")
        return self.code

    def node(self, s):
        k = s[0]
        if k == "let":
            self.expr(s[2])
            if self.locals is not None:
                self.locals[s[1]] = len(self.locals)
                self.emit("STORE", ("local", self.locals[s[1]]))
            else:
                self.emit("STORE", ("global", s[1]))
        elif k == "set":
            self.expr(s[2])
            self.emit("STORE", self.name(s[1]))
        elif k == "istore":
            self.expr(s[3])
            self.emit("LOAD", self.name(s[1]))
            self.expr(s[2])
            self.emit("ISTORE")
        elif k == "if":
            self.expr(s[1])
            j = self.emit("FJUMP")
            for st in s[2]:
                self.node(st)
            if s[3]:
                j2 = self.emit("JUMP")
                self.code[j] = (self.code[j][0], len(self.code))
                for st in s[3]:
                    self.node(st)
                self.code[j2] = (self.code[j2][0], len(self.code))
            else:
                self.code[j] = (self.code[j][0], len(self.code))
        elif k == "while":
            top = len(self.code)
            self.expr(s[1])
            j = self.emit("FJUMP")
            for st in s[2]:
                self.node(st)
            self.emit("JUMP", top)
            self.code[j] = (self.code[j][0], len(self.code))
        elif k == "fn":
            j = self.emit("JUMP")
            self.fns[s[1]] = len(self.code)
            outer = self.locals
            self.locals = {p: i for i, p in enumerate(s[2])}
            for st in s[3]:
                self.node(st)
            self.emit("CONST", 0.0)
            self.emit("RET", len(s[2]))
            self.locals = outer
            self.code[j] = (self.code[j][0], len(self.code))
        elif k == "ret":
            self.expr(s[1])
            n = len(self.locals) if self.locals else 0
            self.emit("RET", n)
        elif k == "print":
            self.expr(s[1])
            self.emit("PRINT")
        elif k == "expr":
            self.expr(s[1])
            self.emit("POP")

    def expr(self, e):
        k = e[0]
        if k == "num":
            self.emit("CONST", e[1])
        elif k == "str":
            self.emit("CONST", e[1])
        elif k == "var":
            self.emit("LOAD", self.name(e[1]))
        elif k == "bin":
            self.expr(e[2])
            self.expr(e[3])
            self.emit(e[1])
        elif k == "neg":
            self.expr(e[1])
            self.emit("NEG")
        elif k == "notx":
            self.expr(e[1])
            self.emit("NOT")
        elif k == "and":
            self.expr(e[1])
            j = self.emit("FJUMP")
            self.expr(e[2])
            self.code[j] = (self.code[j][0], len(self.code))
        elif k == "or":
            self.expr(e[1])
            self.emit("NOT")
            j = self.emit("FJUMP")
            self.expr(e[2])
            self.emit("NOT")
            self.code[j] = (self.code[j][0], len(self.code))
        elif k == "call":
            for a in e[2]:
                self.expr(a)
            self.emit("CALL", (e[1], len(e[2])))
        elif k == "arr":
            for it in e[1]:
                self.expr(it)
            self.emit("ARR", len(e[1]))
        elif k == "idx":
            self.expr(e[1])
            self.expr(e[2])
            self.emit("IDX")
        else:
            raise SyntaxError("cant compile %r" % (e,))


class VM:
    def __init__(self, code, fns, out=None):
        self.code = code
        self.fns = fns
        self.globals = {}
        self.stack = []
        self.frames = []
        self.out = out or (lambda s: print(s))

    def push(self, v):
        self.stack.append(v)

    def pop(self):
        return self.stack.pop()

    def run(self, trace=False):
        ip, n = 0, 0
        while True:
            n += 1
            if n > 5_000_000:
                raise RuntimeError("ran too long, infinite loop?")
            op, arg = self.code[ip]
            ip += 1
            name = OPS[op]
            if trace:
                self.out("%-7s %-14s stack=%s" % (name, arg, self.stack))
            if name == "CONST":
                self.push(arg)
            elif name == "POP":
                self.pop()
            elif name == "LOAD":
                kind, key = arg
                if kind == "local":
                    fr = self.frames[-1]
                    self.push(fr["vars"].get(key, 0.0))
                else:
                    self.push(self.globals.get(key, 0.0))
            elif name == "STORE":
                kind, key = arg
                if kind == "local":
                    self.frames[-1]["vars"][key] = self.pop()
                else:
                    self.globals[key] = self.pop()
            elif name == "ARR":
                items = [self.pop() for _ in range(arg)][::-1]
                self.push(items)
            elif name == "IDX":
                i, arr = int(self.pop()), self.pop()
                self.push(arr[i])
            elif name == "ISTORE":
                i, arr, v = int(self.pop()), self.pop(), self.pop()
                arr[i] = v
            elif name in ("ADD", "SUB", "MUL", "DIV", "MOD"):
                b, a = self.pop(), self.pop()
                if name == "ADD":
                    self.push(VM.show(a) + VM.show(b)
                              if isinstance(a, str) or isinstance(b, str)
                              else a + b)
                elif name == "SUB":
                    self.push(a - b)
                elif name == "MUL":
                    self.push(a * b)
                elif name == "DIV":
                    self.push(a / b)
                else:
                    self.push(a % b)
            elif name == "NEG":
                self.push(-self.pop())
            elif name == "NOT":
                self.push(0.0 if self.pop() else 1.0)
            elif name in ("EQ", "NEQ", "LT", "GT", "LTE", "GTE"):
                b, a = self.pop(), self.pop()
                r = {"EQ": a == b, "NEQ": a != b, "LT": a < b,
                     "GT": a > b, "LTE": a <= b, "GTE": a >= b}[name]
                self.push(1.0 if r else 0.0)
            elif name == "JUMP":
                ip = arg
            elif name == "FJUMP":
                if not self.pop():
                    ip = arg
            elif name == "CALL":
                fname, argc = arg
                args = [self.pop() for _ in range(argc)][::-1]
                if fname not in self.fns:
                    raise RuntimeError("no function called " + fname)
                self.frames.append({"ret": ip,
                                    "vars": {i: v for i, v in enumerate(args)}})
                ip = self.fns[fname]
            elif name == "RET":
                val = self.pop()
                fr = self.frames.pop()
                self.push(val)
                ip = fr["ret"]
            elif name == "PRINT":
                v = self.pop()
                self.out(self.show(v))
            elif name == "HALT":
                return

    @staticmethod
    def show(v):
        if isinstance(v, float) and v == int(v):
            return str(int(v))
        if isinstance(v, list):
            return "[" + ", ".join(VM.show(x) for x in v) + "]"
        return str(v)


def run_src(src, out=None, trace=False):
    toks = lex(src)
    ast = Parser(toks).program()
    c = Compiler()
    code = c.compile(ast)
    VM(code, c.fns, out).run(trace)
    return code, c.fns


def dis(code, fns):
    inv = {v: k for k, v in fns.items()}
    lines = []
    for i, (op, arg) in enumerate(code):
        tag = " <fn %s>" % inv[i] if i in inv else ""
        lines.append("%4d  %-7s %s%s" % (i, OPS[op],
                                         "" if arg is None else arg, tag))
    return "\n".join(lines)


CLI_DEMO = '''let n = 10
let total = 0

fn fib(a, b, steps) {
    print a
    if steps > 0 {
        fib(b, a + b, steps - 1)
    }
}

print "fib:"
fib(0, 1, n)

let i = 0
while i < 5 {
    total = total + i * i
    i = i + 1
}
print "sum of squares: " + total

let arr = [3, 1, 4, 1, 5]
arr[1] = 99
print "arr: " + arr
'''


def main():
    args = sys.argv[1:]
    if "--ide" in args:
        from sparkide import launch
        launch()
        return
    if "--dis" in args:
        args.remove("--dis")
        src = open(args[0], encoding="utf-8").read()
        toks = lex(src)
        c = Compiler()
        code = c.compile(Parser(toks).program())
        print(dis(code, c.fns))
        return
    if args:
        src = open(args[0], encoding="utf-8").read()
        run_src(src)
        return
    print("spark repl (ctrl+c to quit)")
    while True:
        try:
            line = input("> ")
            run_src(line)
        except (KeyboardInterrupt, EOFError):
            break
        except Exception as e:
            print("err:", e)


if __name__ == "__main__":
    main()
