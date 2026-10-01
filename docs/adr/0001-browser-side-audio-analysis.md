# 001. Analyse audio in the browser, not the server

- Status: accepted
- Date: 2026-10-01 (recorded retroactively from the initial implementation)

## Context

Microphone audio has to come from a phone or laptop near the music, not from the host
running the container.

## Decision

The browser captures the mic, runs a Web Audio `AnalyserNode` FFT (4096 points), reduces it
to bass/mid/treble levels in 0..1, and sends only those levels over `/ws`. The server never
sees audio.

## Alternatives considered

- **Stream raw audio to the server**: more bandwidth and latency, a privacy cost, and
  server-side DSP for no benefit.

## Consequences

- Band maths (dB mapping, auto-gain, smoothing) lives in `src/static/live.js`; the server only
  clamps levels to 0..1.
- Mic access needs a secure context, see [0004](0004-https-self-signed-no-auth.md).
