const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    let message = `请求失败: ${response.status}`;
    try {
      const data = await response.json();
      message = data.detail || message;
    } catch {
      message = await response.text();
    }
    throw new Error(message);
  }

  return response.json();
}

export function resolveMediaUrl(asset) {
  if (!asset?.served_url) {
    return asset?.url || "";
  }
  return `${API_BASE}${asset.served_url}`;
}

export function resolveAvatarUrl(url) {
  if (!url) {
    return "";
  }
  if (url.startsWith("/")) {
    return `${API_BASE}${url}`;
  }
  return `${API_BASE}/api/media/proxy?url=${encodeURIComponent(url)}`;
}

export function scrapeAccounts(payload) {
  return request("/api/scrape", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function resolveAccounts(accounts) {
  return request("/api/accounts/resolve", {
    method: "POST",
    body: JSON.stringify({ accounts }),
  });
}

export function getScrapeAccountsConfig() {
  return request("/api/config/scrape-accounts");
}

export function saveScrapeAccountsConfig(accounts) {
  return request("/api/config/scrape-accounts", {
    method: "POST",
    body: JSON.stringify({ accounts }),
  });
}

export function getCookieStatus() {
  return request("/api/auth/cookie/status");
}

export function saveCookieString(cookieString) {
  return request("/api/auth/cookie", {
    method: "POST",
    body: JSON.stringify({ cookie_string: cookieString }),
  });
}

export function searchAccounts(query, limit = 10) {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  return request(`/api/accounts/search?${params.toString()}`);
}

export function getFollowing(page = 1, pageSize = 20) {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  return request(`/api/accounts/following?${params.toString()}`);
}

export function batchFollow(action, targets) {
  return request("/api/accounts/follow", {
    method: "POST",
    body: JSON.stringify({ action, targets }),
  });
}
