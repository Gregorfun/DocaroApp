import http from "k6/http";
import { check, sleep } from "k6";

export const options = {
  vus: Number(__ENV.VUS || 5),
  duration: __ENV.DURATION || "30s",
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<500"],
  },
};

const baseUrl = __ENV.BASE_URL || "http://127.0.0.1:5001";

export default function () {
  const health = http.get(`${baseUrl}/health`);
  check(health, {
    "health status is 200": (r) => r.status === 200,
  });

  const home = http.get(`${baseUrl}/`);
  check(home, {
    "home reachable": (r) => r.status === 200 || r.status === 302,
  });

  sleep(1);
}
