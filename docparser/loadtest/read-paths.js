import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

/**
 * Load test — read paths only.
 *
 * Deliberately excludes uploading. The pipeline this application runs on an
 * upload calls Gemini (billed per document) and posts to SAP, and auto-posting
 * is currently enabled with no value ceiling: a thousand virtual users would
 * create a thousand real invoice documents in the customer's ledger. Load
 * testing that path needs a throwaway configuration, not more virtual users.
 *
 * What is left is still the majority of real traffic — people watching a
 * document process, refreshing the list, and reading the dashboard.
 *
 * Run:
 *   docker run --rm -i --add-host=host.docker.internal:host-gateway \
 *     -e BASE_URL=http://host.docker.internal:8000 \
 *     -e PASSWORD=<super admin password> \
 *     grafana/k6 run - < loadtest/read-paths.js
 */

const BASE = __ENV.BASE_URL || 'http://host.docker.internal:8000';
const EMAIL = __ENV.EMAIL || 'admin@sagetl.com';
const PASSWORD = __ENV.PASSWORD || '';

const loginFailures = new Rate('login_failures');
const documentList = new Trend('document_list_ms', true);
const documentDetail = new Trend('document_detail_ms', true);
const dashboard = new Trend('dashboard_ms', true);

export const options = {
  scenarios: {
    // Ramp rather than a fixed load: the interesting number is where response
    // time starts climbing, not the average at one arbitrary concurrency.
    ramp: {
      executor: 'ramping-vus',
      startVUs: 1,
      stages: [
        { duration: '20s', target: 5 },
        { duration: '30s', target: 20 },
        { duration: '30s', target: 50 },
        { duration: '20s', target: 0 },
      ],
      gracefulRampDown: '10s',
    },
  },
  thresholds: {
    // A person watching a document process polls every two seconds; anything
    // slower than a second makes the interface feel broken.
    'http_req_duration{expected_response:true}': ['p(95)<1000'],
    'http_req_failed': ['rate<0.01'],
    'login_failures': ['rate<0.01'],
    'document_list_ms': ['p(95)<800'],
  },
};

export function setup() {
  if (!PASSWORD) {
    throw new Error('Set PASSWORD to the super-admin password (see apps/api/.env).');
  }
  const res = http.post(`${BASE}/api/auth/login`,
    JSON.stringify({ email: EMAIL, password: PASSWORD }),
    { headers: { 'Content-Type': 'application/json' } });

  if (res.status !== 200) {
    throw new Error(`Login failed (${res.status}). Is the API running on ${BASE}?`);
  }
  const token = res.json('access_token');

  // One document id to exercise the detail path, which is the heaviest read:
  // it returns the extracted fields, the pipeline and every posting record.
  const list = http.get(`${BASE}/api/documents?page=1&limit=1`,
    { headers: { Authorization: `Bearer ${token}` } });
  const docs = list.json('documents') || [];

  return { token, documentId: docs.length ? docs[0].document_id : null };
}

export default function (data) {
  const auth = { headers: { Authorization: `Bearer ${data.token}` } };

  group('document list', () => {
    const res = http.get(`${BASE}/api/documents?page=1&limit=20`, auth);
    documentList.add(res.timings.duration);
    check(res, {
      'list returns 200': (r) => r.status === 200,
      'list has documents array': (r) => Array.isArray(r.json('documents')),
    }) || loginFailures.add(1);
  });

  group('document detail', () => {
    if (!data.documentId) return;
    const res = http.get(`${BASE}/api/documents/${data.documentId}`, auth);
    documentDetail.add(res.timings.duration);
    check(res, { 'detail returns 200': (r) => r.status === 200 });
  });

  group('dashboard metrics', () => {
    const res = http.get(`${BASE}/api/dashboard/metrics`, auth);
    dashboard.add(res.timings.duration);
    check(res, { 'metrics return 200': (r) => r.status === 200 });
  });

  group('mail inbox', () => {
    const res = http.get(`${BASE}/api/documents/from-mail?limit=25`, auth);
    check(res, { 'mail inbox returns 200': (r) => r.status === 200 });
  });

  // Roughly the cadence of the frontend's own polling while a document runs.
  sleep(2);
}
