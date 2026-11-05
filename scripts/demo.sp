let n = 8
fn fib(a, b, s) {
    print a
    if s > 0 { fib(b, a + b, s - 1) }
}
fib(0, 1, n)
