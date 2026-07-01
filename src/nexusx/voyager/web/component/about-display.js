// spec 006 — AboutDisplay
//
// Renders the Python ``__doc__`` of the currently selected schema class as
// GitHub-Flavored Markdown, with Mermaid fences rendered in-place (US2).
//
// Read-only semantics (FR-011 / FR-017): no link navigation; external http(s)
// links open in a new tab with ``rel="noopener"``; all other links render as
// inert ``<a>`` elements. Inner content is sanitized via DOMPurify before
// injection (FR-009).
//
// Props:
//   schemaName: full qualified schema id (module.Class) of the selected entity
//   visible:    whether this tab is currently active (gates fetches)
//
// State is local to the component — no store pollution. Mirrors the
// pattern in related-entities-display.js.

const { defineComponent, ref, watch, onMounted, nextTick } = window.Vue

export default defineComponent({
  name: "AboutDisplay",
  props: {
    schemaName: { type: String, required: true },
    visible: { type: Boolean, default: false },
  },
  setup(props) {
    const docstring = ref("")
    const loading = ref(false)
    const error = ref(null)
    // Tracks which schemaName the cached `docstring` belongs to, so switching
    // tabs away and back doesn't trigger a refetch (spec edge case).
    const loadedFor = ref("")
    // Per-block mermaid parse errors, populated by US2's render pipeline.
    // Kept here even though US1 doesn't use it yet, so US2's extension lands
    // cleanly without restructuring.
    const mermaidErrors = ref([])
    const contentRef = ref(null)

    function computeEmpty() {
      return (
        !loading.value &&
        !error.value &&
        docstring.value !== null &&
        docstring.value.trim() === ""
      )
    }

    async function fetchDocstring() {
      if (!props.schemaName) {
        return
      }
      // Capture at fetch start so we can discard the response if the user
      // switched to another entity while we were awaiting network. Without
      // this guard, a slow fetch for X followed by a switch to Y would let
      // X's response overwrite Y's content briefly (FR-008 strict).
      const requestedSchema = props.schemaName
      loading.value = true
      error.value = null
      try {
        const resp = await fetch("docstring", {
          method: "POST",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ schema_name: requestedSchema }),
        })
        const data = await resp.json().catch(() => ({}))
        // Stale-response guard: if schemaName changed during await, drop the
        // response on the floor — the in-flight fetch for the new entity owns
        // the truth. We intentionally don't touch loading/error here: the
        // new fetch's own state transitions are authoritative.
        if (requestedSchema !== props.schemaName) {
          return
        }
        if (resp.ok) {
          docstring.value = data.docstring || ""
          loadedFor.value = props.schemaName
        } else {
          error.value = (data && data.error) || "Failed to load docstring"
        }
      } catch (e) {
        if (requestedSchema !== props.schemaName) {
          return
        }
        error.value = "Failed to load docstring"
      } finally {
        // Only clear loading if this fetch is still the authoritative one.
        if (requestedSchema === props.schemaName) {
          loading.value = false
        }
      }
    }

    // Determine if a string has any mermaid fences. Used by US1 to short-circuit
    // the (heavier) US2 pipeline when there's nothing to render.
    function hasMermaidFences(text) {
      return /```mermaid\b/.test(text)
    }

    // US1 render pipeline: marked → DOMPurify → inject → harden <a>.
    // US2 will extend this with mermaid.run() per code.language-mermaid block.
    function renderContent() {
      const el = contentRef.value
      if (!el) {
        return
      }
      const raw = docstring.value
      if (!raw || !raw.trim()) {
        el.innerHTML = ""
        return
      }

      // 1. Markdown → HTML
      let html
      try {
        if (window.marked) {
          html = window.marked.parse(raw, { gfm: true, breaks: false })
        } else {
          // Graceful fallback: monospaced pre-formatted text if marked fails to load.
          html = `<pre>${escapeHtml(raw)}</pre>`
        }
      } catch (e) {
        html = `<pre>${escapeHtml(raw)}</pre>`
      }

      // 2. Sanitize (FR-009). Allow class/target/rel/href so mermaid blocks and
      // link hardening survive. Allow <details>/<summary> for US2 error fallback.
      try {
        if (window.DOMPurify) {
          html = window.DOMPurify.sanitize(html, {
            ADD_ATTR: ["class", "target", "rel", "href"],
            ADD_TAGS: ["details", "summary"],
          })
        }
      } catch (e) {
        // If sanitization fails, fall back to escaped plain text rather than
        // injecting potentially unsafe HTML.
        html = `<pre>${escapeHtml(raw)}</pre>`
      }

      // 3. Inject
      el.innerHTML = html

      // 4. Harden all <a> (FR-017): external http(s) opens in new tab with
      // noopener; other links rendered as-is but never trigger entity nav.
      el.querySelectorAll("a").forEach((a) => {
        const href = a.getAttribute("href") || ""
        if (/^https?:\/\//i.test(href)) {
          a.setAttribute("target", "_blank")
          a.setAttribute("rel", "noopener noreferrer")
        }
      })

      // 5. Mermaid (US2). Guard so US1 deployment doesn't crash if the script
      // tag is missing; about-display.js works with or without US2 changes.
      // renderMermaidBlocks is async (awaits Promise-form mermaid.parse in v10+);
      // fire-and-forget here — internal per-block try/catch contains all errors.
      if (hasMermaidFences(raw) && window.mermaid) {
        renderMermaidBlocks(el).catch((e) => {
          console.warn("[about-display] renderMermaidBlocks rejected", e)
        })
      }
    }

    // US2 — extract code.language-mermaid blocks, validate, render.
    // Per-block try/catch (FR-010): one bad block doesn't poison the rest.
    //
    // mermaid v10+ (we pin @11 via CDN) returns a Promise from `parse`, so we
    // await it. `await` on a non-Promise (older versions) resolves immediately,
    // so this code is backward-compatible. The previous sync-only path with
    // `if (result.then) { ...; return }` was buggy: on successful Promise
    // resolution it returned early WITHOUT queueing the block for run(), and
    // users saw raw source instead of diagrams.
    async function renderMermaidBlocks(el) {
      mermaidErrors.value = []
      const blocks = el.querySelectorAll("code.language-mermaid")
      const pending = []
      for (let index = 0; index < blocks.length; index++) {
        const codeEl = blocks[index]
        const source = codeEl.textContent
        const pre = codeEl.parentElement // <pre><code>...</code></pre>
        if (!pre) continue

        try {
          // Throws (or rejects) on syntax error.
          await window.mermaid.parse(source)
        } catch (e) {
          handleMermaidError(pre, source, index, e)
          continue
        }

        // Replace <pre><code ...></code></pre> with <div class="mermaid">src</div>
        const div = document.createElement("div")
        div.className = "mermaid"
        div.textContent = source
        pre.replaceWith(div)
        pending.push(div)
      }

      if (pending.length === 0) {
        return
      }

      // Render all valid blocks in one batch. Failures here (post-parse) are
      // rare; if any slip through, mermaid.run logs to console without crashing.
      try {
        await window.mermaid.run({ nodes: pending })
      } catch (e) {
        console.warn("[about-display] mermaid.run failed", e)
      }
    }

    function handleMermaidError(preEl, source, index, err) {
      const msg = (err && err.message) || String(err)
      mermaidErrors.value.push({ index, message: msg, source })
      const fallback = document.createElement("div")
      fallback.className = "mermaid-error"
      fallback.innerHTML =
        `<p style="color:#c10015; margin:0 0 4px;">该 Mermaid 图渲染失败：${escapeHtml(msg)}</p>` +
        `<details><summary style="cursor:pointer; color:#666;">查看源码</summary>` +
        `<pre style="margin-top:4px;">${escapeHtml(source)}</pre></details>`
      preEl.replaceWith(fallback)
    }

    function escapeHtml(s) {
      return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;")
    }

    function ensureLoaded() {
      if (!props.visible) return
      if (!props.schemaName) return
      if (loadedFor.value === props.schemaName && !error.value) {
        // Already loaded for this entity; just re-render in case DOM was reset.
        nextTick(renderContent)
        return
      }
      fetchDocstring().then(() => {
        nextTick(renderContent)
      })
    }

    watch(() => props.visible, (v) => { if (v) ensureLoaded() })
    watch(() => props.schemaName, () => {
      // Reset cached state on entity switch so the new entity fetches fresh.
      if (props.visible) {
        ensureLoaded()
      } else {
        // Even when hidden, track that we need to refetch on next show.
        loadedFor.value = ""
      }
    })

    onMounted(() => {
      if (props.visible) {
        ensureLoaded()
      }
    })

    return {
      docstring,
      loading,
      error,
      contentRef,
      computeEmpty,
    }
  },
  template: `
  <div class="about-display" style="height:100%; overflow:hidden; background:#fff;">
    <div v-show="loading" style="position:absolute; top:0; left:0; right:0; z-index:10;">
      <q-linear-progress indeterminate color="primary" size="2px" />
    </div>
    <div v-if="error" style="color:#c10015; font-family:Menlo, monospace; font-size:12px; padding:12px 16px;">
      {{ error }}
    </div>
    <div v-else-if="computeEmpty()" class="text-grey-7" style="padding:12px 16px;">
      该实体暂无 docstring。
    </div>
    <div ref="contentRef" class="markdown-body about-markdown-body" style="height:100%; overflow:auto; padding:8px 16px 16px 16px;"></div>
  </div>
  `,
})
