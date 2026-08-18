# Travel Agent v2 Design Docs

## Purpose

This document set defines the new Travel Agent architecture baseline.

The previous architecture was search-first:

User -> Search -> Agent -> Answer

The new architecture is decision-first:

User Intent
-> Candidate Plan
-> Critic
-> Research Router
-> Reality Verification
-> Final Plan

The goal is not to search more information, but to make better travel decisions.
