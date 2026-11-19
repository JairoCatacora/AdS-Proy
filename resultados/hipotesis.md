# Contraste de hipótesis

Nivel de significancia: 0,05. Proporciones con IC de Wilson al 95 %.

## H1 — M2 en P1: A2 > A1
- A2: 18/20 = 90.0 % [IC 95 %: 69.9–97.2 %]
- A1: 0/20 = 0.0 % [IC 95 %: 0.0–16.1 %]
- Prueba exacta de Fisher (una cola, A2 > A1): p = 1.68e-09
- **Se cumple**

## H2 — M1 en P1: A2 = 0 % y A2 < A3
- A2: 0/16 = 0.0 % [IC 95 %: 0.0–19.4 %]
- A3: 16/16 = 100.0 % [IC 95 %: 80.6–100.0 %]
- Prueba exacta de Fisher (una cola, A2 < A3): p = 1.66e-09
- **Se cumple**

## H3 — M6 de A3 > 0
- A3, todos los escenarios: 77/173 confirmaciones revertidas = 44.5 % [IC 95 %: 37.3–52.0 %]
  - P0: 15/31 = 48.4 % [IC 95 %: 32.0–65.2 %]
  - P1: 16/36 = 44.4 % [IC 95 %: 29.5–60.4 %]
  - P2: 16/36 = 44.4 % [IC 95 %: 29.5–60.4 %]
  - P3: 16/36 = 44.4 % [IC 95 %: 29.5–60.4 %]
  - P4: 14/34 = 41.2 % [IC 95 %: 26.4–57.8 %]
- **Se cumple** (límite inferior del IC > 0)

## H4 — M4 (p95 de latencia sin falla): A2 > A1
- A1: p50 50.6 ms, p95 56.3 ms (n = 1000)
- A2: p50 88.7 ms, p95 93.6 ms (n = 1000)
  - líder etcd1: p95 93.2 ms (n = 334)
  - líder etcd2: p95 91.7 ms (n = 333)
  - líder etcd3: p95 94.3 ms (n = 333)
  - líder local al centro que pide: p95 52.0 ms (n = 333)
  - líder remoto al centro que pide: p95 94.0 ms (n = 667)
- A3 (solo reserva local): p95 22.0 ms (n = 1000)
- Mann-Whitney (una cola, A2 > A1): p = 2.26e-85
- **Se cumple**
