// Static throughput baseline used by the sparkline before a run produces
// real history. Once telemetry events arrive, the live ring buffer takes
// over (see store.setTelemetry).
export const SPARKLINE = [
  8.2, 9.1, 9.6, 10.2, 10.8, 11.3, 11.6, 12.0, 12.4, 12.7,
  12.9, 13.1, 13.4, 13.6, 13.8, 14.0, 14.1, 14.2, 14.0, 13.7,
  13.2, 13.0, 13.3, 13.7, 14.1, 14.4, 14.6, 14.5, 14.3, 14.0,
  13.8, 13.6, 13.9, 14.2, 14.5, 14.7, 14.6, 14.4, 14.2, 14.0,
  13.9, 14.0, 14.2, 14.3, 14.4, 14.3, 14.2, 14.1, 14.2, 14.3,
  14.4, 14.2, 14.1, 14.0, 14.1, 14.2, 14.3, 14.2, 14.2, 14.2,
];
