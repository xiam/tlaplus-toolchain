---- MODULE CounterLib ----
EXTENDS Naturals
\* Successor modulo n. Lives in its own module so that a test covers EXTENDS
\* of a sibling module.
Succ(v, n) == (v + 1) % n
====
