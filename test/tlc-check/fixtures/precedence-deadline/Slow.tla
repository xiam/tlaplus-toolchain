---- MODULE Slow ----
\* About 10^12 states: no test waits for the end.
EXTENDS Naturals
VARIABLES x, y
Init == x = 0 /\ y = 0
Next == \/ x' = x + 1 /\ x < 1000000 /\ UNCHANGED y
        \/ y' = y + 1 /\ y < 1000000 /\ UNCHANGED x
====
