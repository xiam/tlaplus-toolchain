---- MODULE Spill ----
\* A grid of N x N small states. TLC keeps its queue of unexplored states
\* on disk, in the scratch directory: about 100 MiB for N = 3000.
EXTENDS Naturals
CONSTANT N
VARIABLES x, y
Init == x = 0 /\ y = 0
Next == \/ x < N /\ x' = x + 1 /\ UNCHANGED y
        \/ y < N /\ y' = y + 1 /\ UNCHANGED x
====
