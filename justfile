# Authenticate gh CLI with a GitHub PAT (token not stored in shell history)
gh-auth:
    #!/bin/bash
    read -sp "GitHub PAT: " t && echo
    echo "$t" | gh auth login --with-token
    unset t
    gh auth setup-git
    gh auth status


# Start Claude Code in sandbox mode (uses container-local SSH agent only)
claude:
    SSH_AUTH_SOCK="/tmp/ssh-agent.sock" IS_SANDBOX=1 claude --dangerously-skip-permissions --chrome
