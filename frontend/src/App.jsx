import { useEffect, useState } from "react";
import {
  CheckSquare,
  ChevronDown,
  Play,
  RefreshCw,
  Save,
  Search,
  UserMinus,
  UserPlus,
  Users,
} from "lucide-react";
import {
  batchFollow,
  getCookieStatus,
  getFollowing,
  getScrapeAccountsConfig,
  resolveAccounts,
  resolveAvatarUrl,
  resolveMediaUrl,
  saveScrapeAccountsConfig,
  saveCookieString,
  scrapeAccounts,
  searchAccounts,
} from "./api";

const DEFAULT_ACCOUNTS = [
  "https://weibo.com/u/3074452897",
  "https://weibo.com/u/1917281600",
  "https://weibo.com/u/2031482343",
].join("\n");

const PAGE_SIZE = 20;
const FOLLOWING_CACHE_KEY = "weibo_craw_following_cache_v1";
const RESOLVE_CACHE_KEY = "weibo_craw_resolve_cache_v1";
const SEARCH_HISTORY_KEY = "weibo_craw_search_history_v1";
const MAX_SEARCH_HISTORY = 20;
const MAX_RESOLVE_CACHE_ITEMS = 12;
const TIME_RANGE_OPTIONS = [
  { label: "三天", amount: 3, unit: "days" },
  { label: "一周", amount: 7, unit: "days" },
  { label: "一个月", amount: 1, unit: "months" },
  { label: "三个月", amount: 3, unit: "months" },
  { label: "半年", amount: 6, unit: "months" },
  { label: "一年", amount: 1, unit: "years" },
  { label: "三年", amount: 3, unit: "years" },
  { label: "十年", amount: 10, unit: "years" },
  { label: "全部时间", unit: "all" },
];

function readLocalJson(key, fallback) {
  if (typeof window === "undefined") {
    return fallback;
  }
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function writeLocalJson(key, value) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(key, JSON.stringify(value));
}

function buildResolveSignature(accounts) {
  return accounts.join("\n");
}

function readResolveCache(signature) {
  const cache = readLocalJson(RESOLVE_CACHE_KEY, {});
  return cache && typeof cache === "object" ? cache[signature] : null;
}

function writeResolveCache(signature, accounts, results) {
  const cache = readLocalJson(RESOLVE_CACHE_KEY, {});
  const nextCache = cache && typeof cache === "object" && !Array.isArray(cache) ? { ...cache } : {};
  nextCache[signature] = {
    accounts,
    results,
    updated_at: new Date().toISOString(),
  };

  const entries = Object.entries(nextCache)
    .sort(([, left], [, right]) => new Date(right.updated_at || 0) - new Date(left.updated_at || 0))
    .slice(0, MAX_RESOLVE_CACHE_ITEMS);
  writeLocalJson(RESOLVE_CACHE_KEY, Object.fromEntries(entries));
}

function parseAccountInput(value) {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatDateTimeLocal(date) {
  const pad = (value) => String(value).padStart(2, "0");
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
  ].join("-") + `T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatDate(value) {
  if (!value) {
    return "未知时间";
  }
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function formatCompactNumber(value) {
  if (value === null || value === undefined) {
    return "--";
  }
  if (value >= 10000) {
    return `${(value / 10000).toFixed(1)}万`;
  }
  return String(value);
}

function IconButton({ children, icon: Icon, ...props }) {
  return (
    <button {...props}>
      {Icon ? <Icon size={16} strokeWidth={2.2} /> : null}
      <span>{children}</span>
    </button>
  );
}

function SentimentBadge({ value }) {
  return <span className={`sentiment sentiment-${value}`}>{value}</span>;
}

function MetricCard({ label, value, hint }) {
  return (
    <div className="metric-card">
      <p>{label}</p>
      <strong>{value}</strong>
      <span>{hint}</span>
    </div>
  );
}

function AccountAvatar({ account, size = 48 }) {
  const [failed, setFailed] = useState(false);
  const label = (account.screen_name || account.uid || account.profile_url || "?").trim().slice(0, 1).toUpperCase();
  const source = resolveAvatarUrl(account.avatar_url);

  if (!source || failed) {
    return (
      <span className="account-avatar account-avatar-fallback" style={{ width: size, height: size }}>
        {label}
      </span>
    );
  }

  return (
    <img
      className="account-avatar"
      src={source}
      alt=""
      style={{ width: size, height: size }}
      onError={() => setFailed(true)}
    />
  );
}

function AuthStatusPill({ status }) {
  if (!status) {
    return <span className="status-pill status-muted">未检测</span>;
  }

  if (status.readable) {
    return (
      <span className="status-pill status-ok">
        {status.source === "manual" ? "手动 Cookie 可用" : "浏览器登录态可用"}
      </span>
    );
  }

  return <span className="status-pill status-error">登录态不可用</span>;
}

function SentimentChart({ analysis }) {
  const rows = [
    { label: "正面", value: analysis.positive_count, className: "tone-positive" },
    { label: "负面", value: analysis.negative_count, className: "tone-negative" },
    { label: "中性", value: analysis.neutral_count, className: "tone-neutral" },
  ];
  const total = rows.reduce((sum, row) => sum + row.value, 0) || 1;

  return (
    <div className="sentiment-chart" aria-label="态度分布">
      {rows.map((row) => (
        <div className="sentiment-row" key={row.label}>
          <span>{row.label}</span>
          <div className="bar-track">
            <div className={`bar-fill ${row.className}`} style={{ width: `${(row.value / total) * 100}%` }} />
          </div>
          <strong>{row.value}</strong>
        </div>
      ))}
    </div>
  );
}

function TopicChart({ topics }) {
  const maxCount = Math.max(...topics.map((item) => item.count), 1);

  if (!topics.length) {
    return <p className="empty-text">暂无高频话题</p>;
  }

  return (
    <div className="topic-chart">
      {topics.map((item) => (
        <div className="topic-row" key={item.topic}>
          <span>{item.topic}</span>
          <div className="bar-track">
            <div className="bar-fill tone-topic" style={{ width: `${(item.count / maxCount) * 100}%` }} />
          </div>
          <strong>{item.count}</strong>
        </div>
      ))}
    </div>
  );
}

function AnalysisPanel({ title, analysis }) {
  if (!analysis) {
    return null;
  }

  return (
    <div className="analysis-panel">
      <div className="section-title compact-title">
        <h4>{title}</h4>
        <SentimentBadge value={analysis.sentiment} />
      </div>
      <p className="summary-text">{analysis.summary}</p>

      <div className="analysis-table-grid">
        <section>
          <h5>态度分布</h5>
          <SentimentChart analysis={analysis} />
        </section>
        <section>
          <h5>高频话题</h5>
          <TopicChart topics={analysis.topic_stats || []} />
        </section>
      </div>

      <table className="viewpoint-table">
        <thead>
          <tr>
            <th>序号</th>
            <th>代表观点</th>
          </tr>
        </thead>
        <tbody>
          {(analysis.viewpoints.length ? analysis.viewpoints : ["暂无代表观点"]).map((viewpoint, index) => (
            <tr key={`${viewpoint}-${index}`}>
              <td>{index + 1}</td>
              <td>{viewpoint}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AccountOption({ account, checked, onToggle }) {
  return (
    <label className={`account-option ${checked ? "account-option-active" : ""}`}>
      <input type="checkbox" checked={checked} onChange={onToggle} />
      <AccountAvatar account={account} />
      <div>
        <strong>{account.screen_name}</strong>
        <a href={account.profile_url} target="_blank" rel="noreferrer">
          {account.profile_url}
        </a>
        <p>{account.intro || "暂无简介"}</p>
        <div className="account-stats">
          <span>粉丝 {formatCompactNumber(account.followers_count)}</span>
          <span>关注 {formatCompactNumber(account.friends_count)}</span>
          <span>微博 {formatCompactNumber(account.statuses_count)}</span>
        </div>
      </div>
    </label>
  );
}

function ResolvePreview({ accounts, loading, error }) {
  if (error && !accounts.length) {
    return <p className="error-text">{error}</p>;
  }

  if (!accounts.length && !loading) {
    return null;
  }

  return (
    <>
      {loading ? <p className="resolve-status">正在重新识别账号...</p> : null}
      {error ? <p className="error-text">{error}</p> : null}
      {accounts.length ? (
        <div className="resolve-preview">
          {accounts.map((account) => (
            <div className={`resolve-item ${account.valid ? "resolve-valid" : "resolve-invalid"}`} key={account.requested_account}>
              {account.valid ? <AccountAvatar account={account} size={40} /> : <span className="resolve-invalid-icon">!</span>}
              <div>
                <strong>{account.valid ? account.screen_name : account.requested_account}</strong>
                <span>{account.valid ? account.profile_url : account.error}</span>
                {account.description ? <p>{account.description}</p> : null}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </>
  );
}

function ResultsSection({ scrapeResult }) {
  if (!scrapeResult) {
    return null;
  }

  return (
    <section className="panel results-panel">
      <div className="section-title">
        <div>
          <h2>抓取结果与分析</h2>
          <p className="section-note">结果区单独占满页面宽度，避免配置栏和账号管理栏被长内容挤压。</p>
        </div>
        <span>生成时间 {formatDate(scrapeResult.generated_at)}</span>
      </div>

      <div className="result-stack">
        {scrapeResult.results.map((account) => (
          <article className="account-card" key={account.uid}>
            <div className="account-header">
              <div>
                <h3>{account.screen_name}</h3>
                <a href={account.profile_url} target="_blank" rel="noreferrer">
                  {account.profile_url}
                </a>
                {account.description ? <p>{account.description}</p> : null}
              </div>
              <div className="account-meta">
                <span>粉丝 {formatCompactNumber(account.followers_count)}</span>
                <span>关注 {formatCompactNumber(account.friends_count)}</span>
                <span>微博 {formatCompactNumber(account.statuses_count)}</span>
              </div>
            </div>

            <div className="analysis-grid">
              <AnalysisPanel title="发博分析" analysis={account.analysis.posts} />
              <AnalysisPanel title="评论分析" analysis={account.analysis.comments} />
            </div>

            {account.export_file ? <p className="export-hint">导出文件：{account.export_file}</p> : null}

            <details className="post-details">
              <summary>查看 {account.posts.length} 条微博明细</summary>
              <div className="post-list">
                {account.posts.map((post) => (
                  <section className="post-card" key={post.id}>
                    <div className="post-head">
                      <strong>{formatDate(post.created_at)}</strong>
                      <span>
                        转发 {post.reposts_count} / 评论 {post.comments_count} / 点赞 {post.attitudes_count}
                      </span>
                    </div>
                    <p>{post.text}</p>

                    {post.images.length ? (
                      <div className="image-grid">
                        {post.images.map((image) => (
                          <a href={resolveMediaUrl(image)} key={image.url} target="_blank" rel="noreferrer">
                            <img src={resolveMediaUrl(image)} alt="微博图片" loading="lazy" />
                          </a>
                        ))}
                      </div>
                    ) : null}

                    {post.comments.length ? (
                      <div className="comment-block">
                        <h4>评论</h4>
                        <ul className="plain-list">
                          {post.comments.map((comment) => (
                            <li key={comment.id}>
                              <strong>{comment.author || "匿名"}</strong>
                              <span>{formatDate(comment.created_at)}</span>
                              <p>{comment.text}</p>
                              {comment.images.length ? (
                                <div className="comment-images">
                                  {comment.images.map((image) => (
                                    <a href={resolveMediaUrl(image)} key={image.url} target="_blank" rel="noreferrer">
                                      查看评论图片
                                    </a>
                                  ))}
                                </div>
                              ) : null}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </section>
                ))}
              </div>
            </details>
          </article>
        ))}
      </div>
    </section>
  );
}

function App() {
  const [scrapeForm, setScrapeForm] = useState({
    accounts: DEFAULT_ACCOUNTS,
    maxPosts: 20,
    startTime: "",
    endTime: "",
    fetchComments: true,
    maxCommentsPerPost: 20,
    downloadImages: true,
  });
  const [scrapeLoading, setScrapeLoading] = useState(false);
  const [scrapeError, setScrapeError] = useState("");
  const [scrapeResult, setScrapeResult] = useState(null);
  const [resolvedAccounts, setResolvedAccounts] = useState([]);
  const [resolveLoading, setResolveLoading] = useState(false);
  const [resolveError, setResolveError] = useState("");
  const [accountConfigLoaded, setAccountConfigLoaded] = useState(false);
  const [accountConfigMessage, setAccountConfigMessage] = useState("");
  const [authStatus, setAuthStatus] = useState(null);
  const [cookieString, setCookieString] = useState("");
  const [authLoading, setAuthLoading] = useState(false);
  const [authMessage, setAuthMessage] = useState("");
  const [authPanelOpen, setAuthPanelOpen] = useState(false);
  const [accountEditorOpen, setAccountEditorOpen] = useState(false);
  const [accountManagerOpen, setAccountManagerOpen] = useState(false);

  const [accountMode, setAccountMode] = useState("following");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [searchHistory, setSearchHistory] = useState(() => {
    const cached = readLocalJson(SEARCH_HISTORY_KEY, []);
    return Array.isArray(cached) ? cached : [];
  });
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [searchResult, setSearchResult] = useState([]);
  const [followingCache, setFollowingCache] = useState(() => {
    const cached = readLocalJson(FOLLOWING_CACHE_KEY, null);
    return cached?.result ? cached : null;
  });
  const [followingLoading, setFollowingLoading] = useState(false);
  const [followingError, setFollowingError] = useState("");
  const [followingPage, setFollowingPage] = useState(() => followingCache?.page || 1);
  const [followingResult, setFollowingResult] = useState(() => followingCache?.result || null);
  const [selectedTargets, setSelectedTargets] = useState([]);
  const [followLoading, setFollowLoading] = useState(false);
  const [followResult, setFollowResult] = useState(null);

  const visibleAccounts = accountMode === "following" ? followingResult?.items || [] : searchResult;
  const selectedVisibleAccounts = visibleAccounts.filter((account) => selectedTargets.includes(account.profile_url));
  const selectedCount = selectedVisibleAccounts.length;
  const accountInputCount = parseAccountInput(scrapeForm.accounts).length;

  useEffect(() => {
    loadCookieStatus();
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadScrapeAccountsConfig() {
      try {
        const data = await getScrapeAccountsConfig();
        if (cancelled) {
          return;
        }
        if (data.accounts?.length) {
          setScrapeForm((current) => ({ ...current, accounts: data.accounts.join("\n") }));
          setAccountConfigMessage(`已从本地文件读取 ${data.accounts.length} 个账号。`);
        } else {
          setAccountConfigMessage("暂无本地账号配置，当前默认账号会自动保存到本地文件。");
        }
      } catch (error) {
        if (!cancelled) {
          setAccountConfigMessage(`读取本地账号配置失败：${error.message}`);
        }
      } finally {
        if (!cancelled) {
          setAccountConfigLoaded(true);
        }
      }
    }

    loadScrapeAccountsConfig();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const accounts = parseAccountInput(scrapeForm.accounts);
    if (!accounts.length) {
      setResolvedAccounts([]);
      setResolveError("");
      setResolveLoading(false);
      return undefined;
    }

    const signature = buildResolveSignature(accounts);
    const cached = readResolveCache(signature);
    if (Array.isArray(cached?.results)) {
      setResolvedAccounts(cached.results);
    } else {
      setResolvedAccounts([]);
    }
    setResolveError("");

    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setResolveLoading(true);
      setResolveError("");
      try {
        const data = await resolveAccounts(accounts);
        if (!cancelled) {
          setResolvedAccounts(data);
          writeResolveCache(signature, accounts, data);
        }
      } catch (error) {
        if (!cancelled) {
          setResolveError(error.message);
          if (!Array.isArray(cached?.results)) {
            setResolvedAccounts([]);
          }
        }
      } finally {
        if (!cancelled) {
          setResolveLoading(false);
        }
      }
    }, 650);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [scrapeForm.accounts]);

  useEffect(() => {
    if (!accountConfigLoaded) {
      return undefined;
    }

    let cancelled = false;
    const timer = window.setTimeout(async () => {
      const accounts = parseAccountInput(scrapeForm.accounts);
      try {
        const data = await saveScrapeAccountsConfig(accounts);
        if (!cancelled) {
          setAccountConfigMessage(`已保存 ${data.accounts.length} 个账号到本地文件。`);
        }
      } catch (error) {
        if (!cancelled) {
          setAccountConfigMessage(`保存账号配置失败：${error.message}`);
        }
      }
    }, 700);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [scrapeForm.accounts, accountConfigLoaded]);

  const totals = !scrapeResult
    ? { accounts: 0, posts: 0, comments: 0 }
    : {
        accounts: scrapeResult.total_accounts,
        posts: scrapeResult.total_posts,
        comments: scrapeResult.results.reduce(
          (sum, account) => sum + account.posts.reduce((count, post) => count + post.comments.length, 0),
          0,
        ),
      };

  async function loadCookieStatus() {
    setAuthLoading(true);
    setAuthMessage("");
    try {
      const data = await getCookieStatus();
      setAuthStatus(data);
      setCookieString(data.cookie_string || "");
      setAuthMessage(data.message);
    } catch (error) {
      setAuthMessage(error.message);
    } finally {
      setAuthLoading(false);
    }
  }

  async function handleCookieSave(event) {
    event.preventDefault();
    setAuthLoading(true);
    setAuthMessage("");
    try {
      const data = await saveCookieString(cookieString);
      setAuthStatus(data);
      setCookieString(data.cookie_string || cookieString);
      setAuthMessage(data.message);
    } catch (error) {
      setAuthMessage(error.message);
    } finally {
      setAuthLoading(false);
    }
  }

  async function handleScrapeSubmit(event) {
    event.preventDefault();
    setScrapeLoading(true);
    setScrapeError("");
    setScrapeResult(null);

    const accounts = parseAccountInput(scrapeForm.accounts);

    try {
      const data = await scrapeAccounts({
        accounts,
        max_posts: scrapeForm.maxPosts ? Number(scrapeForm.maxPosts) : null,
        start_time: scrapeForm.startTime || null,
        end_time: scrapeForm.endTime || null,
        fetch_comments: scrapeForm.fetchComments,
        max_comments_per_post: Number(scrapeForm.maxCommentsPerPost),
        download_images: scrapeForm.downloadImages,
        save_json: true,
      });
      setScrapeResult(data);
    } catch (error) {
      setScrapeError(error.message);
    } finally {
      setScrapeLoading(false);
    }
  }

  async function handleSearchSubmit(event) {
    event.preventDefault();
    await runAccountSearch(searchKeyword);
  }

  async function runAccountSearch(query) {
    const normalizedQuery = query.trim();
    if (!normalizedQuery) {
      return;
    }
    setAccountMode("search");
    setSearchKeyword(normalizedQuery);
    setSearchLoading(true);
    setSearchError("");
    setFollowResult(null);

    try {
      const data = await searchAccounts(normalizedQuery, 12);
      setSearchResult(data);
      setSelectedTargets([]);
      setSearchHistory((current) => {
        const history = Array.isArray(current) ? current : [];
        const next = [normalizedQuery, ...history.filter((item) => item !== normalizedQuery)].slice(0, MAX_SEARCH_HISTORY);
        writeLocalJson(SEARCH_HISTORY_KEY, next);
        return next;
      });
    } catch (error) {
      setSearchError(error.message);
    } finally {
      setSearchLoading(false);
    }
  }

  function clearSearchHistory() {
    setSearchHistory([]);
    writeLocalJson(SEARCH_HISTORY_KEY, []);
  }

  function showFollowingMode() {
    setAccountMode("following");
    if (!followingResult && followingCache?.result) {
      setFollowingResult(followingCache.result);
      setFollowingPage(followingCache.page || followingCache.result.page || 1);
    }
  }

  async function loadFollowing(page = followingPage, clearFollowResult = true) {
    setAccountMode("following");
    setFollowingLoading(true);
    setFollowingError("");
    if (clearFollowResult) {
      setFollowResult(null);
    }

    try {
      const data = await getFollowing(page, PAGE_SIZE);
      setFollowingResult(data);
      setFollowingPage(page);
      const nextCache = { page, result: data, cached_at: new Date().toISOString() };
      setFollowingCache(nextCache);
      writeLocalJson(FOLLOWING_CACHE_KEY, nextCache);
      setSelectedTargets([]);
    } catch (error) {
      setFollowingError(error.message);
    } finally {
      setFollowingLoading(false);
    }
  }

  async function handleBatchAction(action) {
    const targets = selectedVisibleAccounts.map((account) => account.profile_url);
    if (!targets.length) {
      return;
    }
    setFollowLoading(true);
    setSearchError("");
    setFollowingError("");
    setFollowResult(null);

    try {
      const data = await batchFollow(action, targets);
      if (action === "unfollow" && accountMode === "following") {
        await loadFollowing(followingPage, false);
      }
      setFollowResult(data);
    } catch (error) {
      if (accountMode === "following") {
        setFollowingError(error.message);
      } else {
        setSearchError(error.message);
      }
    } finally {
      setFollowLoading(false);
    }
  }

  function toggleTarget(target) {
    setSelectedTargets((current) =>
      current.includes(target) ? current.filter((item) => item !== target) : [...current, target],
    );
  }

  function toggleAllVisible() {
    const targets = visibleAccounts.map((account) => account.profile_url);
    const allSelected = targets.length > 0 && targets.every((target) => selectedTargets.includes(target));
    setSelectedTargets((current) => {
      if (allSelected) {
        return current.filter((target) => !targets.includes(target));
      }
      return [...new Set([...current, ...targets])];
    });
  }

  function addAccountsToScrapeList(accounts) {
    const urls = accounts
      .map((account) => account.profile_url || (account.uid ? `https://weibo.com/u/${account.uid}` : ""))
      .filter(Boolean);
    if (!urls.length) {
      return;
    }

    setScrapeForm((current) => {
      const existing = parseAccountInput(current.accounts);
      const merged = [...new Set([...existing, ...urls])];
      return { ...current, accounts: merged.join("\n") };
    });
  }

  function addSelectedVisibleToScrapeList() {
    addAccountsToScrapeList(selectedVisibleAccounts);
  }

  function applyTimeRange(option) {
    if (option.unit === "all") {
      setScrapeForm((current) => ({ ...current, startTime: "", endTime: "" }));
      return;
    }

    const end = new Date();
    const start = new Date(end);
    if (option.unit === "days") {
      start.setDate(start.getDate() - option.amount);
    }
    if (option.unit === "months") {
      start.setMonth(start.getMonth() - option.amount);
    }
    if (option.unit === "years") {
      start.setFullYear(start.getFullYear() - option.amount);
    }

    setScrapeForm((current) => ({
      ...current,
      startTime: formatDateTimeLocal(start),
      endTime: formatDateTimeLocal(end),
    }));
  }

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <span className="eyebrow">React + FastAPI + Playwright + JIEBA</span>
          <h1>微博作战台</h1>
          <p>批量抓取微博内容与评论，管理关注列表，并以图表和表格查看账号话题、观点和态度。</p>
        </div>
        <div className="hero-grid">
          <MetricCard label="账号数" value={totals.accounts} hint="本次抓取结果" />
          <MetricCard label="博文数" value={totals.posts} hint="满足筛选条件" />
          <MetricCard label="评论数" value={totals.comments} hint="已抓取评论" />
        </div>
      </header>

      <section className="panel auth-panel">
        <div className="section-title collapsible-title">
          <div>
            <h2>登录态设置</h2>
            <p className="section-note">
              Edge 已登录只说明浏览器可访问微博。后端需要读取微博 Cookie；如果 Cookie 数据库被 Windows 锁定，就需要在这里填写一次请求 Cookie。
            </p>
          </div>
          <div className="title-actions">
            <AuthStatusPill status={authStatus} />
            <button
              aria-expanded={authPanelOpen}
              className="collapse-toggle"
              type="button"
              onClick={() => setAuthPanelOpen((current) => !current)}
            >
              <ChevronDown className={authPanelOpen ? "collapse-icon open" : "collapse-icon"} size={16} />
              <span>{authPanelOpen ? "收起设置" : "展开设置"}</span>
            </button>
          </div>
        </div>

        {authPanelOpen ? (
          <div className="auth-grid">
            <div className="auth-guide">
              <ol className="tutorial-list">
                <li>在 Edge 打开微博页面并保持登录。</li>
                <li>按 F12 打开开发者工具，进入“网络 / Network”，刷新页面。</li>
                <li>
                  点开任意 <code>weibo.com/ajax/...</code> 请求，在 Request Headers 中复制 <code>Cookie</code> 整行内容。
                </li>
                <li>粘贴到右侧输入框，点击“保存 Cookie”。</li>
              </ol>
              <p className="auth-message">{authMessage || "Cookie 保存在本机 backend/.env，可在此处查看和更新。"}</p>
            </div>

            <form className="auth-form" onSubmit={handleCookieSave}>
              <label className="field">
                <span>微博请求 Cookie</span>
                <textarea
                  rows="4"
                  value={cookieString}
                  onChange={(event) => setCookieString(event.target.value)}
                  placeholder="SUB=...; XSRF-TOKEN=...; ..."
                />
              </label>
              <div className="actions">
                <IconButton className="primary-button" icon={Save} type="submit" disabled={authLoading || !cookieString.trim()}>
                  {authLoading ? "处理中" : "保存 Cookie"}
                </IconButton>
                <IconButton className="ghost-button" icon={RefreshCw} type="button" disabled={authLoading} onClick={loadCookieStatus}>
                  检测登录态
                </IconButton>
              </div>
            </form>
          </div>
        ) : null}
      </section>

      <main className="dashboard">
        <section className="panel scrape-panel">
          <div className="section-title">
            <h2>抓取配置</h2>
            <span>按账号、数量和时间范围抓取</span>
          </div>
          <form className="form-grid" onSubmit={handleScrapeSubmit}>
            <div className="field field-span collapsible-field">
              <div className="field-collapse-head">
                <div>
                  <span>微博账号 URL / UID</span>
                  <p>已填写 {accountInputCount} 个账号，展开后可编辑或粘贴多行。</p>
                  {accountConfigMessage ? <p>{accountConfigMessage}</p> : null}
                </div>
                <button
                  aria-expanded={accountEditorOpen}
                  className="collapse-toggle"
                  type="button"
                  onClick={() => setAccountEditorOpen((current) => !current)}
                >
                  <ChevronDown className={accountEditorOpen ? "collapse-icon open" : "collapse-icon"} size={16} />
                  <span>{accountEditorOpen ? "收起账号" : "展开账号"}</span>
                </button>
              </div>
              {accountEditorOpen ? (
                <>
                  <textarea
                    rows="5"
                    value={scrapeForm.accounts}
                    onChange={(event) => setScrapeForm((current) => ({ ...current, accounts: event.target.value }))}
                    placeholder="每行一个账号"
                  />
                  <ResolvePreview accounts={resolvedAccounts} loading={resolveLoading} error={resolveError} />
                </>
              ) : null}
            </div>

            <label className="field">
              <span>最多抓取博文数</span>
              <input
                type="number"
                min="1"
                max="200"
                value={scrapeForm.maxPosts}
                onChange={(event) => setScrapeForm((current) => ({ ...current, maxPosts: event.target.value }))}
              />
            </label>

            <label className="field">
              <span>每条博文评论上限</span>
              <input
                type="number"
                min="0"
                max="100"
                value={scrapeForm.maxCommentsPerPost}
                onChange={(event) =>
                  setScrapeForm((current) => ({ ...current, maxCommentsPerPost: event.target.value }))
                }
              />
            </label>

            <label className="field">
              <span>开始时间</span>
              <input
                type="datetime-local"
                value={scrapeForm.startTime}
                onChange={(event) => setScrapeForm((current) => ({ ...current, startTime: event.target.value }))}
              />
            </label>

            <label className="field">
              <span>结束时间</span>
              <input
                type="datetime-local"
                value={scrapeForm.endTime}
                onChange={(event) => setScrapeForm((current) => ({ ...current, endTime: event.target.value }))}
              />
            </label>

            <div className="time-presets field-span">
              <span>快捷时间范围</span>
              <div>
                {TIME_RANGE_OPTIONS.map((option) => (
                  <button type="button" key={option.label} onClick={() => applyTimeRange(option)}>
                    {option.label}
                  </button>
                ))}
              </div>
            </div>

            <label className="switch">
              <input
                type="checkbox"
                checked={scrapeForm.fetchComments}
                onChange={(event) =>
                  setScrapeForm((current) => ({ ...current, fetchComments: event.target.checked }))
                }
              />
              <span>抓取评论</span>
            </label>

            <label className="switch">
              <input
                type="checkbox"
                checked={scrapeForm.downloadImages}
                onChange={(event) =>
                  setScrapeForm((current) => ({ ...current, downloadImages: event.target.checked }))
                }
              />
              <span>下载图片到本地</span>
            </label>

            <div className="actions field-span">
              <IconButton className="primary-button" icon={Play} type="submit" disabled={scrapeLoading}>
                {scrapeLoading ? "抓取中" : "开始抓取"}
              </IconButton>
              {scrapeError ? <p className="error-text">{scrapeError}</p> : null}
            </div>
          </form>
        </section>

        <section className="panel account-manager">
          <div className="section-title collapsible-title">
            <div>
              <h2>账号管理</h2>
              <span>搜索账号或从我的关注中批量取关</span>
            </div>
            <button
              aria-expanded={accountManagerOpen}
              className="collapse-toggle"
              type="button"
              onClick={() => setAccountManagerOpen((current) => !current)}
            >
              <ChevronDown className={accountManagerOpen ? "collapse-icon open" : "collapse-icon"} size={16} />
              <span>{accountManagerOpen ? "收起管理" : "展开管理"}</span>
            </button>
          </div>

          {accountManagerOpen ? (
            <>
              <div className="segmented-control">
                <button
                  className={accountMode === "following" ? "active" : ""}
                  type="button"
                  onClick={showFollowingMode}
                >
                  <Users size={16} />
                  <span>我的关注</span>
                </button>
                <button
                  className={accountMode === "search" ? "active" : ""}
                  type="button"
                  onClick={() => setAccountMode("search")}
                >
                  <Search size={16} />
                  <span>搜索账号</span>
                </button>
              </div>

              {accountMode === "search" ? (
                <>
                  <form className="inline-form" onSubmit={handleSearchSubmit}>
                    <input
                      type="text"
                      value={searchKeyword}
                      onChange={(event) => setSearchKeyword(event.target.value)}
                      placeholder="输入微博昵称、关键词、UID"
                    />
                    <IconButton className="primary-button" icon={Search} type="submit" disabled={searchLoading || !searchKeyword.trim()}>
                      {searchLoading ? "搜索中" : "搜索账号"}
                    </IconButton>
                  </form>
                  {searchHistory.length ? (
                    <div className="search-history">
                      <span>搜索历史</span>
                      <div>
                        {searchHistory.map((item) => (
                          <button type="button" key={item} disabled={searchLoading} onClick={() => runAccountSearch(item)}>
                            {item}
                          </button>
                        ))}
                        <button className="clear-history-button" type="button" onClick={clearSearchHistory}>
                          清空
                        </button>
                      </div>
                    </div>
                  ) : null}
                </>
              ) : (
                <div className="following-header">
                  <div className="following-meta">
                    <strong>{followingResult?.screen_name || "当前登录账号"}</strong>
                    <span>关注总数 {followingResult ? followingResult.total_number : "--"}</span>
                    <span className="following-note">（若包含已注销账号，该数目可能不准确）</span>
                  </div>
                  <IconButton className="primary-button" icon={RefreshCw} type="button" disabled={followingLoading} onClick={() => loadFollowing(1)}>
                    {followingLoading ? "加载中" : "加载关注列表"}
                  </IconButton>
                </div>
              )}

              <div className="toolbar account-toolbar">
                <span>已选中 {selectedCount} 个账号</span>
                <div className="actions account-toolbar-actions">
                  <IconButton
                    className="ghost-button"
                    icon={CheckSquare}
                    type="button"
                    disabled={!visibleAccounts.length}
                    onClick={toggleAllVisible}
                  >
                    全选列表
                  </IconButton>
                  {accountMode === "search" ? (
                    <IconButton
                      className="secondary-button"
                      icon={UserPlus}
                      type="button"
                      disabled={followLoading || !selectedCount}
                      onClick={() => handleBatchAction("follow")}
                    >
                      批量关注
                    </IconButton>
                  ) : null}
                  <IconButton
                    className="ghost-button"
                    icon={UserMinus}
                    type="button"
                    disabled={followLoading || !selectedCount}
                    onClick={() => handleBatchAction("unfollow")}
                  >
                    批量取关
                  </IconButton>
                  <IconButton
                    className="secondary-button"
                    icon={Play}
                    type="button"
                    disabled={!selectedCount}
                    onClick={addSelectedVisibleToScrapeList}
                  >
                    加入待爬取
                  </IconButton>
                </div>
              </div>

              {searchError && accountMode === "search" ? <p className="error-text">{searchError}</p> : null}
              {followingError && accountMode === "following" ? <p className="error-text">{followingError}</p> : null}

              <div className="account-list">
                {visibleAccounts.map((account) => (
                  <AccountOption
                    account={account}
                    checked={selectedTargets.includes(account.profile_url)}
                    key={account.profile_url}
                    onToggle={() => toggleTarget(account.profile_url)}
                  />
                ))}
                {!visibleAccounts.length ? <p className="empty-text">当前列表暂无账号。</p> : null}
              </div>

              {accountMode === "following" && followingResult ? (
                <div className="pagination">
                  <button type="button" disabled={followingLoading || followingPage <= 1} onClick={() => loadFollowing(followingPage - 1)}>
                    上一页
                  </button>
                  <span>第 {followingPage} 页</span>
                  <button type="button" disabled={followingLoading || !followingResult.has_next} onClick={() => loadFollowing(followingPage + 1)}>
                    下一页
                  </button>
                </div>
              ) : null}

              {followResult ? (
                <div className="follow-result">
                  <p>
                    本次 {followResult.action === "follow" ? "关注" : "取关"} 完成：成功 {followResult.success_count}，
                    失败 {followResult.failure_count}
                  </p>
                  <ul className="plain-list">
                    {followResult.items.map((item) => (
                      <li key={`${item.target}-${item.detail}`}>
                        <strong>{item.target}</strong> - {item.status} - {item.detail}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </>
          ) : null}
        </section>
      </main>

      <ResultsSection scrapeResult={scrapeResult} />
    </div>
  );
}

export default App;
