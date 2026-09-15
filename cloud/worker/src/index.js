/**
 * videogen 云端渲染网关（Cloudflare Worker）
 *
 * 职责：把工作台前端和 GitHub 连起来
 *   素材包 zip  -> GitHub Release 资产（bundle 区）
 *   触发渲染    -> workflow_dispatch（.github/workflows/render.yml）
 *   进度查询    -> Actions run 状态
 *   成片取回    -> Release 资产流式代理（私有仓库需带 token）
 *
 * 需要的环境变量 / secrets：
 *   GITHUB_TOKEN  必填，细粒度 PAT：Actions(读写) + Contents(读写)
 *   REPO          可选，默认 bopii6/videogen
 *   BUNDLE_TAG    可选，素材包存放的 release tag，默认 bundles
 */

const GH = "https://api.github.com";
const UPLOADS = "https://uploads.github.com";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const cors = {
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET,POST,OPTIONS",
      "access-control-allow-headers": "content-type,x-bundle-name",
      "access-control-max-age": "86400",
    };
    if (request.method === "OPTIONS") return new Response(null, { headers: cors });

    const repo = env.REPO || "bopii6/videogen";
    const bundleTag = env.BUNDLE_TAG || "bundles";
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
        const rel = await gh(`/repos/${repo}/releases/tags/${bundleTag}`);
        if (rel.status === 404) return json({ bundles: [] });
        const data = await rel.json();
        return json({
          bundles: (data.assets || [])
            .filter((a) => a.name.endsWith(".zip"))
            .map((a) => ({ name: a.name.replace(/\.zip$/, ""), asset: a.name, size: a.size, created: a.created_at }))
            .sort((a, b) => (a.created < b.created ? 1 : -1)),
        });
      }

      // ---------- 上传素材包 ----------
      if (url.pathname === "/api/upload" && request.method === "POST") {
        const raw = request.headers.get("x-bundle-name") || `bundle-${Date.now()}`;
        const name = decodeURIComponent(raw).replace(/[^\w\u4e00-\u9fa5.-]/g, "_").replace(/\.zip$/, "");
        const body = await request.arrayBuffer();
        if (!body.byteLength) return json({ error: "空文件" }, 400);
        if (body.byteLength > 200 * 1024 * 1024) return json({ error: "zip 超过 200MB" }, 413);

        // 滚动 release：没有就建（prerelease，避免污染"最新发布"）
        let rel = await gh(`/repos/${repo}/releases/tags/${bundleTag}`);
        if (rel.status === 404) {
          const create = await gh(`/repos/${repo}/releases`, {
            method: "POST",
            body: JSON.stringify({ tag_name: bundleTag, name: "素材包", body: "工作台上传的素材包（滚动更新）", prerelease: true }),
          });
          if (!create.ok) return json({ error: "无法创建素材包区", detail: await create.text() }, 502);
          rel = create;
        }
        const release = await rel.json();

        const assetName = `${name}.zip`;
        const existing = (release.assets || []).find((a) => a.name === assetName);
        if (existing) await gh(`/repos/${repo}/releases/assets/${existing.id}`, { method: "DELETE" });

        const up = await fetch(`${UPLOADS}/repos/${repo}/releases/${release.id}/assets?name=${encodeURIComponent(assetName)}`, {
          method: "POST",
          headers: {
            authorization: `Bearer ${token}`,
            "content-type": "application/zip",
            "user-agent": "videogen-worker",
          },
          body,
        });
        if (!up.ok) return json({ error: "上传失败", detail: (await up.text()).slice(0, 300) }, 502);
        return json({ ok: true, name, asset: assetName });
      }

      // ---------- 触发渲染 ----------
      if (url.pathname === "/api/render" && request.method === "POST") {
        const req = await request.json();
        if (!req.bundle) return json({ error: "缺少素材包" }, 400);
        const job = crypto.randomUUID().replace(/-/g, "").slice(0, 12);
        const dispatch = await gh(`/repos/${repo}/actions/workflows/render.yml/dispatches`, {
          method: "POST",
          body: JSON.stringify({
            ref: "main",
            inputs: {
              job_id: job,
              bundle_tag: bundleTag,
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
        return json({ ok: true, job, note: req.bundle });
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
