---- MODULE Counter ----
\* A counter that counts from 0 to N - 1 and wraps around to 0.
EXTENDS Naturals
CONSTANT N
VARIABLE x

Init == x = 0
Next == x' = (x + 1) % N

TypeOK == x \in 0..(N - 1)
====
