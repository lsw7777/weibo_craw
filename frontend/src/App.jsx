import { useEffect, useState } from "react";
import {
  batchFollow,
  getCookieStatus,
  resolveMediaUrl,
  saveCookieString,
  scrapeAccounts,
  searchAccounts,
} from "./api";

const DEFAULT_ACCOUNTS = [
  "https://weibo.com/u/3074452897",
  "https://weibo.com/u/1917281600",
  "https://weibo.com/u/2031482343",
].join("\n");

function formatDate(value) {
  if (!value) {
    return "未知时间";
  }
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
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

function AnalysisPanel({ title, analysis }) {
  if (!analysis) {
    return null;
  }

  return (
    <div className="analysis-panel">
      <div className="section-title">
        <h4>{title}</h4>
        <SentimentBadge value={analysis.sentiment} />
      </div>
      <p>{analysis.summary}</p>
      <div className="chip-group">
        {analysis.topics.map((topic) => (
          <span className="chip" key={topic}>
            {topic}
          </span>
        ))}
      </div>
      <ul className="plain-list">
        {analysis.viewpoints.map((viewpoint) => (
          <li key={viewpoint}>{viewpoint}</li>
        ))}
      </ul>
    </div>
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
  const [authStatus, setAuthStatus] = useState(null);
  const [cookieString, setCookieString] = useState("");
  const [authLoading, setAuthLoading] = useState(false);
  const [authMessage, setAuthMessage] = useState("");

  const [searchKeyword, setSearchKeyword] = useState("");
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [searchResult, setSearchResult] = useState([]);
  const [selectedTargets, setSelectedTargets] = useState([]);
  const [followLoading, setFollowLoading] = useState(false);
  const [followResult, setFollowResult] = useState(null);

  const selectedCount = selectedTargets.length;

  useEffect(() => {
    loadCookieStatus();
  }, []);

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
      setCookieString("");
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

    const accounts = scrapeForm.accounts
      .split(/\r?\n|,/)
      .map((item) => item.trim())
      .filter(Boolean);

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
    setSearchLoading(true);
    setSearchError("");
    setFollowResult(null);

    try {
      const data = await searchAccounts(searchKeyword, 12);
      setSearchResult(data);
      setSelectedTargets([]);
    } catch (error) {
      setSearchError(error.message);
    } finally {
      setSearchLoading(false);
    }
  }

  async function handleBatchAction(action) {
    if (!selectedTargets.length) {
      return;
    }
    setFollowLoading(true);
    setSearchError("");
    setFollowResult(null);

    try {
      const data = await batchFollow(action, selectedTargets);
      setFollowResult(data);
    } catch (error) {
      setSearchError(error.message);
    } finally {
      setFollowLoading(false);
    }
  }

  function toggleTarget(target) {
    setSelectedTargets((current) =>
      current.includes(target) ? current.filter((item) => item !== target) : [...current, target],
    );
  }

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <span className="eyebrow">React + FastAPI + Playwright</span>
          <h1>微博作战台</h1>
          <p>批量抓取微博内容与评论，下载图片，搜索账号并执行批量关注/取关，同时输出话题、观点和态度摘要。</p>
        </div>
        <div className="hero-grid">
          <MetricCard label="账号数" value={totals.accounts} hint="本次抓取结果" />
          <MetricCard label="博文数" value={totals.posts} hint="满足筛选条件" />
          <MetricCard label="评论数" value={totals.comments} hint="已抓取评论" />
        </div>
      </header>

      <section className="panel auth-panel">
        <div className="section-title">
          <div>
            <h2>登录态设置</h2>
            <p className="section-note">
              Edge 已登录只说明浏览器可访问微博。后端需要读取微博 Cookie；如果 Cookie 数据库被 Windows 锁定，就需要在这里填写一次请求 Cookie。
            </p>
          </div>
          <AuthStatusPill status={authStatus} />
        </div>

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
            <p className="auth-message">{authMessage || "Cookie 只保存在本机 backend/.env，前端不会回显完整 Cookie。"}</p>
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
              <button className="primary-button" type="submit" disabled={authLoading || !cookieString.trim()}>
                {authLoading ? "处理中..." : "保存 Cookie"}
              </button>
              <button className="ghost-button" type="button" disabled={authLoading} onClick={loadCookieStatus}>
                检测登录态
              </button>
            </div>
          </form>
        </div>
      </section>

      <main className="dashboard">
        <section className="panel">
          <div className="section-title">
            <h2>抓取与分析</h2>
            <span>按账号批量拉取博文、评论和图片</span>
          </div>
          <form className="form-grid" onSubmit={handleScrapeSubmit}>
            <label className="field field-span">
              <span>微博账号 URL / UID</span>
              <textarea
                rows="5"
                value={scrapeForm.accounts}
                onChange={(event) => setScrapeForm((current) => ({ ...current, accounts: event.target.value }))}
                placeholder="每行一个账号"
              />
            </label>

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
              <button className="primary-button" type="submit" disabled={scrapeLoading}>
                {scrapeLoading ? "抓取中..." : "开始抓取"}
              </button>
              {scrapeError ? <p className="error-text">{scrapeError}</p> : null}
            </div>
          </form>

          {scrapeResult ? (
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
                      <span>粉丝 {account.followers_count ?? "--"}</span>
                      <span>关注 {account.friends_count ?? "--"}</span>
                      <span>微博 {account.statuses_count ?? "--"}</span>
                    </div>
                  </div>

                  <div className="analysis-grid">
                    <AnalysisPanel title="发博分析" analysis={account.analysis.posts} />
                    <AnalysisPanel title="评论分析" analysis={account.analysis.comments} />
                  </div>

                  {account.export_file ? <p className="export-hint">导出文件：{account.export_file}</p> : null}

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
                                        <a
                                          href={resolveMediaUrl(image)}
                                          key={image.url}
                                          target="_blank"
                                          rel="noreferrer"
                                        >
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
                </article>
              ))}
            </div>
          ) : null}
        </section>

        <section className="panel">
          <div className="section-title">
            <h2>账号搜索与关注管理</h2>
            <span>搜索后选择多个账号，一次执行关注或取关</span>
          </div>

          <form className="inline-form" onSubmit={handleSearchSubmit}>
            <input
              type="text"
              value={searchKeyword}
              onChange={(event) => setSearchKeyword(event.target.value)}
              placeholder="输入微博昵称、关键词、UID"
            />
            <button className="primary-button" type="submit" disabled={searchLoading}>
              {searchLoading ? "搜索中..." : "搜索账号"}
            </button>
          </form>

          <div className="toolbar">
            <span>已选中 {selectedCount} 个账号</span>
            <div className="actions">
              <button
                className="secondary-button"
                type="button"
                disabled={followLoading || !selectedCount}
                onClick={() => handleBatchAction("follow")}
              >
                批量关注
              </button>
              <button
                className="ghost-button"
                type="button"
                disabled={followLoading || !selectedCount}
                onClick={() => handleBatchAction("unfollow")}
              >
                批量取关
              </button>
            </div>
          </div>

          {searchError ? <p className="error-text">{searchError}</p> : null}

          <div className="search-result-grid">
            {searchResult.map((account) => {
              const checked = selectedTargets.includes(account.profile_url);
              return (
                <label className={`search-card ${checked ? "search-card-active" : ""}`} key={account.profile_url}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleTarget(account.profile_url)}
                  />
                  <div>
                    <strong>{account.screen_name}</strong>
                    <a href={account.profile_url} target="_blank" rel="noreferrer">
                      {account.profile_url}
                    </a>
                    {account.intro ? <p>{account.intro}</p> : null}
                  </div>
                </label>
              );
            })}
          </div>

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
        </section>
      </main>
    </div>
  );
}

export default App;
