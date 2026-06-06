const BASE = '/api';

function formatError(body, status) {
  if (!body) return `Error del servidor (${status})`;
  if (typeof body === 'string') return body;
  if (body.detail) return body.detail;
  if (body.error) return body.error;
  if (body.non_field_errors) {
    const msgs = Array.isArray(body.non_field_errors)
      ? body.non_field_errors
      : [body.non_field_errors];
    return msgs.join(' ');
  }
  const parts = [];
  for (const [field, errors] of Object.entries(body)) {
    if (field === 'non_field_errors') continue;
    const msgs = Array.isArray(errors) ? errors : [errors];
    const label = field === '__all__' ? '' : `${field}: `;
    parts.push(`${label}${msgs.join(', ')}`);
  }
  if (parts.length > 0) return parts.join(' | ');
  return `Error desconocido (${status})`;
}

function buildUrl(endpoint) {
  if (endpoint.startsWith('http://') || endpoint.startsWith('https://')) {
    const url = new URL(endpoint);
    if (url.pathname.startsWith(`${BASE}/`)) {
      return `${url.pathname}${url.search}`;
    }
    return endpoint;
  }
  return `${BASE}/${endpoint}`;
}

async function request(method, endpoint, data = null, options = {}) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (data !== null) opts.body = JSON.stringify(data);

  const res = await fetch(buildUrl(endpoint), opts);

  let body = null;
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) body = await res.json();

  if (!res.ok) throw new Error(formatError(body, res.status));

  if (
    method === 'GET' &&
    options.fetchAll &&
    body &&
    typeof body === 'object' &&
    Array.isArray(body.results)
  ) {
    const results = [...body.results];
    let next = body.next;
    while (next) {
      const nextPage = await request('GET', next, null, { fetchAll: false });
      if (!nextPage || !Array.isArray(nextPage.results)) break;
      results.push(...nextPage.results);
      next = nextPage.next;
    }
    return results;
  }

  if (body && typeof body === 'object' && Array.isArray(body.results)) {
    return options.rawPage ? body : body.results;
  }
  return body;
}

export const api = {
  get: (ep) => request('GET', ep, null, { fetchAll: true }),
  getPage: (ep) => request('GET', ep, null, { rawPage: true }),
  post: (ep, data) => request('POST', ep, data),
  patch: (ep, data) => request('PATCH', ep, data),
  put: (ep, data) => request('PUT', ep, data),
  delete: (ep) => request('DELETE', ep),
};

export function withQuery(endpoint, params) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    query.set(key, value);
  }
  const qs = query.toString();
  return qs ? `${endpoint}?${qs}` : endpoint;
}
