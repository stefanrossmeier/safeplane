The developer models can be selected via environment variables.

Currently only openrouter is configured via API key.

Example:
export SAFEPLANE_MODEL_PROFILE_DEVELOPER_DOCUMENTATION='openrouter/google/gemini-3.1-flash-lite'
export SAFEPLANE_MODEL_PROFILE_DEVELOPER_ANALYSIS='openrouter/deepseek/deepseek-v3.1-terminus'
export SAFEPLANE_MODEL_PROFILE_DEVELOPER_PLANNING='openrouter/deepseek/deepseek-v3.1-terminus'
export SAFEPLANE_MODEL_PROFILE_DEVELOPER_IMPLEMENTATION='openrouter/qwen/qwen3-coder-30b-a3b-instruct'
export SAFEPLANE_MODEL_PROFILE_DEVELOPER_REVIEW='openrouter/deepseek/deepseek-v3.1-terminus'
export SAFEPLANE_MODEL_PROFILE_DEVELOPER_PR='openrouter/google/gemini-3.1-flash-lite'



export SAFEPLANE_MODEL_PROFILE_DEVELOPER_DOCUMENTATION='openrouter/openai/gpt-5-mini'
export SAFEPLANE_MODEL_PROFILE_DEVELOPER_ANALYSIS='openrouter/anthropic/claude-haiku-4.5'
export SAFEPLANE_MODEL_PROFILE_DEVELOPER_PLANNING='openrouter/anthropic/claude-sonnet-4.6'
export SAFEPLANE_MODEL_PROFILE_DEVELOPER_IMPLEMENTATION='openrouter/openai/gpt-5-mini'
export SAFEPLANE_MODEL_PROFILE_DEVELOPER_REVIEW='openrouter/anthropic/claude-haiku-4.5'
export SAFEPLANE_MODEL_PROFILE_DEVELOPER_PR='openrouter/openai/gpt-5.4-nano'