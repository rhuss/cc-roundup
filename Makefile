.PHONY: validate test install uninstall reinstall install-codex help

MARKETPLACE := cc-roundup-plugin-development
PLUGIN := cc-roundup@$(MARKETPLACE)

validate:
	claude plugin validate ./
	claude plugin validate ./roundup/

test:
	python3 -m unittest discover -s tests -t .

install:
	@if claude plugin marketplace add ./ 2>&1 | grep -q "already installed"; then \
		echo "Updating marketplace..."; \
		claude plugin marketplace update $(MARKETPLACE); \
	else \
		echo "Marketplace added."; \
	fi
	@if claude plugin list 2>/dev/null | grep -q "$(PLUGIN)"; then \
		echo "Plugin already installed, reinstalling..."; \
		claude plugin rm $(PLUGIN) 2>/dev/null || true; \
	fi
	claude plugin install $(PLUGIN)

install-codex:
	codex plugin marketplace add $(CURDIR)
	codex plugin install $(PLUGIN)

uninstall:
	@echo "Removing plugin..."
	@claude plugin rm $(PLUGIN) 2>/dev/null || echo "Plugin not installed"
	@echo "Removing marketplace..."
	@claude plugin marketplace rm $(MARKETPLACE) 2>/dev/null || echo "Marketplace not installed"

reinstall: uninstall install

help:
	@echo "Available targets:"
	@echo "  validate      - Validate plugin manifests (Claude Code)"
	@echo "  test          - Run the offline test suite (no Corgi, network or clipboard)"
	@echo "  install       - Install plugin via Claude Code marketplace"
	@echo "  install-codex - Install plugin via Codex marketplace"
	@echo "  uninstall     - Remove plugin and marketplace (Claude Code)"
	@echo "  reinstall     - Full uninstall and reinstall"
