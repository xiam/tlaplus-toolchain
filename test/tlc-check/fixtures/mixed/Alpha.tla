---- MODULE Alpha ----
EXTENDS Naturals
VARIABLE x
Init == x = 0
Next == x' = (x + 1) % 10
\* Alphaated in the sixth state.
Small == x < 10
====
