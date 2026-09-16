/**
 * videogen 云端渲染网关（Cloudflare Worker）
 *
 * 职责：把工作台前端（同 Worker 托管的静态页）和 GitHub 连起来
 *   素材包 zip  -> GitHub Release（每个素材包一个 release：bundle-<slug>）
 *   触发渲染    -> workflow_dispatch（.github/workflows/render.yml）
 *   进度查询    -> Actions run 状态
 *   成片取回    -> Release 资产流式代理（私有仓库需带 token）
 *
 * 需要的环境变量 / secrets：
 *   GITHUB_TOKEN  必填，PAT：Actions(读写) + Contents(读写)
 *   REPO          可选，默认 bopii6/videogen
 */

// 界面直接打进 Worker 返回（不启用 Cloudflare 静态资源，避免它消费请求体）
import uiHtml from "./ui.html";

const GH = "https://api.github.com";
const UPLOADS = "https://uploads.github.com";

/**
 * GitHub Release 的资产名不支持中文（会被改写成 "."），所以：
 * 原始名只放在 release 标题里，真正落盘的名字用确定性 ASCII slug。
 * 同名重传命中同一个 slug，实现覆盖更新。
 */
function slugify(name) {
  const ascii = name.toLowerCase().replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "").slice(0, 24);
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.codePointAt(0)) >>> 0;
  return `${ascii || "bundle"}-${h.toString(36)}`;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    console.log("REQ", request.method, url.pathname,
                "cl=" + (request.headers.get("content-length") || "-"));
    const cors = {
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET,POST,OPTIONS",
      "access-control-allow-headers": "content-type,x-bundle-name",
      "access-control-max-age": "86400",
    };
    if (request.method === "OPTIONS") return new Response(null, { headers: cors });

    // ---------- 工作台界面（直接由 Worker 返回）----------
    if (!url.pathname.startsWith("/api/")) {
      if (url.pathname === "/" || url.pathname === "/index.html") {
        return new Response(uiHtml, {
          headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-cache" },
        });
      }
      return new Response("not found", { status: 404, headers: { "content-type": "text/plain; charset=utf-8" } });
    }

    const repo = env.REPO || "bopii6/videogen";
    const token = env.GITHUB_TOKEN;

    const json = (data, status = 200) =>
      new Response(JSON.stringify(data), {
        status,
        headers: { "content-type": "application/json; charset=utf-8", ...cors },
      });

    if (!token) return json({ error: "Worker 未配置 GITHUB_TOKEN" }, 500);

    const gh = (path, init = {}) =>
      fetch(GH + path, {
        ...init,
        headers: {
          authorization: `Bearer ${token}`,
          accept: "application/vnd.github+json",
          "user-agent": "videogen-worker",
          "x-github-api-version": "2022-11-28",
          ...(init.headers || {}),
        },
      });

    try {
      // ---------- 健康检查 ----------
      if (url.pathname === "/api/health") {
        const r = await gh(`/repos/${repo}`);
        return json({ ok: r.ok, repo, status: r.status });
      }

      // ---------- 素材包列表 ----------
      if (url.pathname === "/api/bundles" && request.method === "GET") {
        const rel = await gh(`/repos/${repo}/releases?per_page=50`);
        const list = (await rel.json()) || [];
        return json({
          bundles: list
            .filter((r) => r.tag_name.startsWith("bundle-"))
            .map((r) => {
              const asset = (r.assets || []).find((a) => a.name.endsWith(".zip"));
              return {
                slug: r.tag_name.replace(/^bundle-/, ""),
                name: r.name || r.tag_name.replace(/^bundle-/, ""),
                asset: asset ? asset.name : null,
                size: asset ? asset.size : 0,
                created: r.published_at,
              };
            })
            .filter((b) => b.asset)
            .sort((a, b) => (a.created < b.created ? 1 : -1)),
        });
      }

      // ---------- 上传素材包 ----------
      if (url.pathname === "/api/upload" && request.method === "POST") {
        let raw = `bundle-${Date.now()}`;
        try {
          raw = decodeURIComponent(request.headers.get("x-bundle-name") || raw);
        } catch { /* 非法编码时用默认名 */ }
        const display = raw.replace(/\.zip$/i, "").trim().slice(0, 60) || "bundle";
        const slug = slugify(display);
        const tag = `bundle-${slug}`;

        // 大文件不能先缓冲到内存（Cloudflare 会先把大 body 缓冲一遍，
        // 之后 arrayBuffer() 会报 "Body has already been used"）。
        // 直接把请求体作为数据流转交给 GitHub，全程不落地。
        const declaredLength = Number(request.headers.get("content-length") || 0);
        if (!request.body) return json({ error: "请求体为空" }, 400);
        if (declaredLength > 200 * 1024 * 1024) return json({ error: "zip 超过 200MB" }, 413);

        let rel = await gh(`/repos/${repo}/releases/tags/${tag}`);
        if (rel.status === 404) {
          rel = await gh(`/repos/${repo}/releases`, {
            method: "POST",
            body: JSON.stringify({
              tag_name: tag, name: display,
              body: "由工作台上传的素材包", prerelease: true,
            }),
          });
          if (!rel.ok) return json({ error: "无法创建素材包", detail: (await rel.text()).slice(0, 300) }, 502);
        } else {
          const cur = await rel.json();
          await gh(`/repos/${repo}/releases/${cur.id}`, {
            method: "PATCH", body: JSON.stringify({ name: display }),
          });
        }
        const release = await rel.json();

        const assetName = `${slug}.zip`;
        const existing = (release.assets || []).find((a) => a.name === assetName);
        if (existing) await gh(`/repos/${repo}/releases/assets/${existing.id}`, { method: "DELETE" });

        const upHeaders = {
          authorization: `Bearer ${token}`,
          "content-type": "application/zip",
          "user-agent": "videogen-worker",
        };
        if (declaredLength) upHeaders["content-length"] = String(declaredLength);

        const up = await fetch(
          `${UPLOADS}/repos/${repo}/releases/${release.id}/assets?name=${encodeURIComponent(assetName)}`,
          { method: "POST", headers: upHeaders, body: request.body, duplex: "half" },
        );
        if (!up.ok) return json({ error: "上传失败", detail: (await up.text()).slice(0, 300) }, 502);
        return json({ ok: true, slug, name: display, asset: assetName });
      }

      // ---------- 触发渲染 ----------
      if (url.pathname === "/api/render" && request.method === "POST") {
        const req = await request.json();
        if (!req.bundle) return json({ error: "缺少素材包" }, 400);
        const slug = String(req.bundle);
        const job = crypto.randomUUID().replace(/-/g, "").slice(0, 12);
        const dispatch = await gh(`/repos/${repo}/actions/workflows/render.yml/dispatches`, {
          method: "POST",
          body: JSON.stringify({
            ref: "main",
            inputs: {
              job_id: job,
              bundle_tag: `bundle-${slug}`,
              format: req.format || "portrait_editorial",
              voice: req.voice || "",
              rate: req.rate || "",
              bgm: req.bgm || "",
              subtitles: req.subtitles === false ? "off" : "on",
              sources: req.sources === false ? "off" : "on",
              sfx: req.sfx === false ? "off" : "on",
              use_llm: req.useLlm === false ? "off" : "on",
            },
          }),
        });
        if (!dispatch.ok) return json({ error: "触发失败", detail: (await dispatch.text()).slice(0, 300) }, 502);
        return json({ ok: true, job, slug });
      }

      // ---------- 进度查询 ----------
      if (url.pathname === "/api/status" && request.method === "GET") {
        const job = url.searchParams.get("job") || "";
        if (!job) return json({ error: "缺少 job" }, 400);

        const runs = await gh(`/repos/${repo}/actions/workflows/render.yml/runs?per_page=30`);
        const list = (await runs.json()).workflow_runs || [];
        const run = list.find((r) => r.display_title === `render ${job}`);
        if (!run) return json({ stage: "queued", job });

        const head = await gh(`/repos/${repo}/actions/runs/${run.id}/jobs`);
        const steps = ((await head.json()).jobs || [])
          .flatMap((j) => (j.steps || []).map((s) => ({ name: s.name, status: s.status, conclusion: s.conclusion })));

        let stage = "running";
        if (run.status === "completed") stage = run.conclusion === "success" ? "done" : "failed";
        const done = steps.filter((s) => s.status === "completed").length;
        return json({
          stage,
          job,
          run_id: run.id,
          run_url: run.html_url,
          steps,
          progress: steps.length ? Math.round((done / steps.length) * 100) : 0,
        });
      }

      // ---------- 取回成片（代理 release 资产）----------
      if (url.pathname === "/api/video" && request.method === "GET") {
        const job = url.searchParams.get("job") || "";
        const rel = await gh(`/repos/${repo}/releases/tags/render-${job}`);
        if (rel.status === 404) return json({ error: "成片还没好" }, 404);
        const release = await rel.json();
        const asset = (release.assets || []).find((a) => a.name.endsWith(".mp4"));
        if (!asset) return json({ error: "该任务没有成片（渲染可能失败）", run_url: release.html_url }, 404);

        const bin = await fetch(`${GH}/repos/${repo}/releases/assets/${asset.id}`, {
          headers: { authorization: `Bearer ${token}`, accept: "application/octet-stream", "user-agent": "videogen-worker" },
        });
        if (!bin.ok) return json({ error: "读取成片失败" }, 502);
        return new Response(bin.body, {
          headers: {
            "content-type": "video/mp4",
            "content-length": String(asset.size),
            "content-disposition": `inline; filename="${job}.mp4"`,
            "cache-control": "no-store",
            ...cors,
          },
        });
      }

      // ---------- 历史成片 ----------
      if (url.pathname === "/api/renders" && request.method === "GET") {
        const rel = await gh(`/repos/${repo}/releases?per_page=30`);
        const list = (await rel.json()) || [];
        return json({
          renders: list
            .filter((r) => r.tag_name.startsWith("render-"))
            .map((r) => ({
              job: r.tag_name.replace(/^render-/, ""),
              title: r.name,
              notes: r.body,
              created: r.published_at,
              has_video: (r.assets || []).some((a) => a.name.endsWith(".mp4")),
            })),
        });
      }

      return json({ error: "not found" }, 404);
    } catch (e) {
      return json({ error: String(e && e.message ? e.message : e) }, 500);
    }
  },
};
