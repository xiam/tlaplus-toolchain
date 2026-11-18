---- MODULE Hog ----
\* Each state doubles the length of a sequence, so the Java heap is
\* exhausted after a few dozen states, whatever the budget.
EXTENDS Sequences
VARIABLE s
Init == s = <<0>>
Next == s' = s \o s
====
