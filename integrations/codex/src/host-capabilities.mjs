/**
 * Declarative host-capability export for the Codex adapter.
 *
 * This is documentation-as-code: every true value below is backed by a public
 * Codex 0.163 hook or app-server contract that the adapter actually uses.
 * Unsupported capabilities are false rather than simulated.
 */
export const HOST_CAPABILITIES = Object.freeze({
  adapter: 'codex',
  host: 'Codex CLI / Codex App hooks',
  protocol_version: 1,
  hook_events: Object.freeze({
    post_tool_use: true,
    session_start: true,
    session_end: true,
    user_prompt_submit: true,
    stop: true,
    interrupt: true,
    pre_tool_use: true,
    permission_request: true,
    pre_compact: true,
    post_compact: true,
    subagent_start: true,
    subagent_stop: true,
  }),
  adapter_uses_events: Object.freeze(['PostToolUse']),
  tool_result_observation: true,
  context_injection: Object.freeze({
    post_tool_use_additional_context: true,
    session_start_additional_context: true,
    user_prompt_submit_additional_context: true,
  }),
  committed_message_receipt: false,
  tool_visibility_query: false,
  permission_confirmation: false,
  cancellation: false,
  reliable_task_outcome: false,
  native_panel: false,
  skill_loading: Object.freeze({
    user_skills_root: '$CODEX_HOME/skills',
    app_server_list: 'skills/list',
    verified_scope: 'user',
  }),
  mcp_tools: true,
  notify: Object.freeze({
    available: true,
    used_by_adapter: false,
    limitation: 'notify is turn-level and cannot inject context into the current model step',
  }),
  app_server: Object.freeze({
    available: true,
    used_by_installer: true,
    used_by_hook: false,
    methods: Object.freeze(['hooks/list', 'skills/list', 'config/batchWrite']),
  }),
  limitations: Object.freeze([
    'hooks do not expose per-agent tool visibility',
    'hook output acceptance is not acknowledged by the host',
    'Bash PostToolUse payload is a string without a structured exit code in 0.163.0-alpha.11',
    'transport-level MCP failures were not observed through PostToolUse in this version',
    'Stop is not a task-success signal',
    'no native settings-panel contract is claimed',
  ]),
});
