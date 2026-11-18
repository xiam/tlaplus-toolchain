---- MODULE Counter ----
EXTENDS Naturals, CounterLib
CONSTANT N
VARIABLE x
Init == x = 0
Next == x' = Succ(x, N)
TypeOK == x \in 0..(N - 1)
====
