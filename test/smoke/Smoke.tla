------------------------------- MODULE Smoke -------------------------------
(* A tiny spec with a known state space, used to prove that the image runs *)
(* TLC. Two counters x and y each step from 0 to N; from (N, N) both reset *)
(* to 0, so no state deadlocks. The reachable states are 0..N \X 0..N:     *)
(* (N + 1)^2 distinct states, 16 for N = 3.                                *)
EXTENDS Naturals

CONSTANT N

VARIABLES x, y

vars == <<x, y>>

TypeOK == x \in 0..N /\ y \in 0..N

Init == x = 0 /\ y = 0

IncX == x < N /\ x' = x + 1 /\ UNCHANGED y

IncY == y < N /\ y' = y + 1 /\ UNCHANGED x

Reset == x = N /\ y = N /\ x' = 0 /\ y' = 0

Next == IncX \/ IncY \/ Reset

Spec == Init /\ [][Next]_vars
=============================================================================
