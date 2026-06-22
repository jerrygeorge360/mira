# Provisional and Confirmed Memory

## Status

Accepted

## Context

Immediate extraction is useful but may be incomplete, corrected, or session-local.

## Decision

Session items are provisional; durable memory requires slow-path confirmation.

## Consequences

Promotions are evidence-gated, rejections do not rewrite observations, and corrections apply forward.

