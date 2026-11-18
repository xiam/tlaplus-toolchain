---- MODULE Omega ----
EXTENDS Naturals
VARIABLE x
Init == x = 0
Next == x' = (x + 1) % 10
\* Omegaated in the sixth state.
Small == x < 10
====
