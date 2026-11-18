---- MODULE Viol ----
EXTENDS Naturals
VARIABLE x
Init == x = 0
Next == x' = (x + 1) % 10
\* Violated in the sixth state.
Small == x < 5
====
