# Contraste de hipótesis

> **Piloto:** 2–3 ensayos por celda. Estos valores solo prueban el análisis; no deben interpretarse.

Nivel de significancia: 0,05. Proporciones con IC de Wilson al 95 %.

## H1 — M2 en P1: A2 > A1
- A2: 3/3 = 100.0 % [IC 95 %: 43.8–100.0 %]
- A1: 0/3 = 0.0 % [IC 95 %: 0.0–56.2 %]
- Prueba exacta de Fisher (una cola, A2 > A1): p = 0.05
- **No se cumple**

## H2 — M1 en P1: A2 = 0 % y A2 < A3
- A2: 0/2 = 0.0 % [IC 95 %: 0.0–65.8 %]
- A3: 2/2 = 100.0 % [IC 95 %: 34.2–100.0 %]
- Prueba exacta de Fisher (una cola, A2 < A3): p = 0.167
- **No se cumple**

## H3 — M6 de A3 > 0
- A3, todos los escenarios: 11/26 confirmaciones revertidas = 42.3 % [IC 95 %: 25.5–61.1 %]
  - P0: 3/6 = 50.0 % [IC 95 %: 18.8–81.2 %]
  - P1: 2/5 = 40.0 % [IC 95 %: 11.8–76.9 %]
  - P2: 2/5 = 40.0 % [IC 95 %: 11.8–76.9 %]
  - P3: 2/5 = 40.0 % [IC 95 %: 11.8–76.9 %]
  - P4: 2/5 = 40.0 % [IC 95 %: 11.8–76.9 %]
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
