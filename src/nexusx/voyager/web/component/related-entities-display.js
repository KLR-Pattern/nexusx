import { store } from "../store.js"

const { defineComponent, ref, watch, onMounted, onBeforeUnmount, nextTick, computed } = window.Vue

// spec 005 — RelatedEntitiesDisplay
//
// Renders a read-only mini ER sub-graph (selected entity + direct neighbors)
// using its own d3-graphviz instance. Reuses the main graph's rendering config
// (show_module / show_methods / edge_minlen / show_fields) by reading from the
// shared store.filter, so config changes on the main panel automatically
// re-fetch and re-render this sub-graph (FR-015).
//
// Read-only semantics (FR-007 / FR-016): no node/edge click handlers are bound;
// d3-graphviz's built-in pan/zoom remains enabled.
//
// Props:
//   schemaName: full qualified schema id (module.Class) of the selected entity
//   visible:    whether this tab is currently active (gates fetches)

// Per-instance counter so each mounted component gets its own graphviz container.
let _relatedEntitiesUid = 0

export default defineComponent({
  name: "RelatedEntitiesDisplay",
  props: {
    schemaName: { type: String, required: true },
    visible: { type: Boolean, default: true },
  },
  setup(props) {
    const uid = ++_relatedEntitiesUid
    const containerId = `related-entities-graph-${uid}`

    const dot = computed(() => store.state.relatedEntities.dot)
    const loading = computed(() => store.state.relatedEntities.loading)
    const error = computed(() => store.state.relatedEntities.error)
    const schemas = computed(() => store.state.relatedEntities.schemas)
    // Isolated entity: a valid DOT was returned but it only describes the selected
    // entity itself (no incident edges). Overlay a "no relations" hint on the graph.
    const isEmpty = computed(
      () => !error.value && !!dot.value && schemas.value.length <= 1
    )

    let graphvizInstance = null

    function renderDot() {
      if (!dot.value) {
        return
      }
      const el = document.getElementById(containerId)
      if (!el) {
        return
      }
      try {
        if (!graphvizInstance) {
          graphvizInstance = window.d3.select(`#${containerId}`).graphviz({
            zoom: true,
            fit: true,
            useWorker: false,
          })
        }
        // d3-graphviz only honors `fit` when width/height are set: it then keeps
        // graphviz's own viewBox and lets the SVG (preserveAspectRatio) scale the
        // graph down to the container. Without this the sub-graph renders at its
        // natural size and overflows the sidebar. Mirrors GraphUI.render().
        graphvizInstance
          .width("100%")
          .height("100%")
          .fit(true)
          .transition(() => null)
          .renderDot(dot.value)
          .on("end", () => {
            // Re-center on every (re)render so switching entities/tabs doesn't
            // inherit a previous pan/zoom transform.
            graphvizInstance.resetZoom()
          })
      } catch (e) {
        console.warn("[related-entities] render failed", e)
      }
    }

    function triggerFetch(force = false) {
      if (!props.visible || !props.schemaName) {
        return
      }
      if (force) {
        // Invalidate cache so the dedup guard in fetchRelatedEntities lets us refetch
        // (used when render config changed and the cached dot is now stale).
        store.state.relatedEntities.selectedSchema = ""
      }
      store.actions.fetchRelatedEntities(props.schemaName)
    }

    // FR-011 / FR-004: selection change → refetch.
    watch(() => props.schemaName, () => triggerFetch(false))

    // Tab activation: if becoming visible with stale data, refetch; else re-render.
    watch(
      () => props.visible,
      (v) => {
        if (!v) {
          return
        }
        if (store.state.relatedEntities.selectedSchema !== props.schemaName) {
          triggerFetch(false)
        } else {
          nextTick(renderDot)
        }
      }
    )

    // New DOT arrived → render.
    watch(dot, () => {
      if (props.visible) {
        nextTick(renderDot)
      }
    })

    // FR-015: render config changes on the main panel → invalidate + refetch.
    watch(
      () => [
        store.state.filter.showFields,
        store.state.filter.showModule,
        store.state.filter.edgeMinlen,
        store.state.filter.showMethods,
      ],
      () => triggerFetch(true)
    )

    onMounted(() => {
      if (props.visible) {
        triggerFetch(false)
      }
    })

    onBeforeUnmount(() => {
      graphvizInstance = null
      const el = document.getElementById(containerId)
      if (el) {
        el.innerHTML = ""
      }
    })

    return { containerId, loading, error, isEmpty }
  },
  template: `
  <div class="frv-related-entities" style="position:relative; height:100%; background:#fff;">
    <div v-show="loading" style="position:absolute; top:0; left:0; right:0; z-index:10;">
      <q-linear-progress indeterminate color="primary" size="2px"/>
    </div>
    <div v-if="error" style="padding:16px; color:#c10015; font-family:Menlo, monospace; font-size:12px;">
      {{ error }}
    </div>
    <template v-else>
      <div :id="containerId" style="width:100%; height:100%;"></div>
      <div
        v-if="isEmpty && !loading"
        style="position:absolute; top:50%; left:50%; transform:translate(-50%,-50%); color:#666; font-style:italic; pointer-events:none; text-align:center; font-size:12px;"
      >
        该实体没有直接关联实体
      </div>
    </template>
  </div>
  `,
})
