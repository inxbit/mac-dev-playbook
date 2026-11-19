#!/usr/bin/env bash
# Set up a fresh Mac from this playbook and a private dotfiles repository that
# holds config.yml as a Stow package.
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/inxbit/mac-dev-playbook/master/bootstrap.sh)"
#
# Run it from a terminal, not through `curl | bash`: the Command Line Tools
# dialog, sudo, the GitHub login and the playbook's become prompt all need you.
# Each step is skipped when it is already done, so a rerun is safe. Arguments
# go to ansible-playbook, for example `bootstrap.sh --skip-tags mas` (pass them
# after a placeholder $0 when using `bash -c`: `bash -c "$(curl ...)" - --skip-tags mas`).
set -euo pipefail

PLAYBOOK_REPO=${PLAYBOOK_REPO:-https://github.com/inxbit/mac-dev-playbook.git}
PLAYBOOK_DIR=${PLAYBOOK_DIR:-$HOME/Documents/Projects/mac-dev-playbook}
DOTFILES_REPO=${DOTFILES_REPO:-inxbit/dotfiles}
DOTFILES_DIR=${DOTFILES_DIR:-$HOME/dotfiles}
CONFIG_PACKAGE=${CONFIG_PACKAGE:-mac-dev-playbook}

step() { printf '\n==> %s\n' "$*"; }
die() {
  printf 'bootstrap: %s\n' "$*" >&2
  exit 1
}

[[ $(uname -s) == Darwin ]] || die "this script only runs on macOS."
[[ $EUID -ne 0 ]] || die "run it as your normal user, not with sudo."
[[ -t 0 ]] || die "run it from a terminal with bash -c \"\$(curl ...)\", not curl | bash."

# sudo asks a paired smart card for its PIN before the password, and the
# playbook hands its become password to sudo non-interactively.
if security list-smartcards 2>/dev/null | grep -q ':'; then
  die "unplug your smart card (YubiKey) first, then rerun."
fi

step "Command Line Tools"
if ! xcode-select -p >/dev/null 2>&1; then
  xcode-select --install || true
  read -r -p "Finish the Command Line Tools installer, then press Return. "
  xcode-select -p >/dev/null 2>&1 || die "the Command Line Tools are still missing."
fi

step "Rosetta"
if [[ $(uname -m) == arm64 ]] && ! /usr/bin/arch -x86_64 /usr/bin/true 2>/dev/null; then
  sudo softwareupdate --install-rosetta --agree-to-license
fi

step "Homebrew"
if [[ ! -x /opt/homebrew/bin/brew ]]; then
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
eval "$(/opt/homebrew/bin/brew shellenv)"
for formula in ansible gh stow; do
  brew list --formula "$formula" >/dev/null 2>&1 || brew install "$formula"
done

step "GitHub login"
gh auth status >/dev/null 2>&1 || gh auth login --hostname github.com --git-protocol https --web

step "Playbook checkout"
[[ -d $PLAYBOOK_DIR/.git ]] || git clone "$PLAYBOOK_REPO" "$PLAYBOOK_DIR"

step "Dotfiles checkout"
[[ -d $DOTFILES_DIR/.git ]] || gh repo clone "$DOTFILES_REPO" "$DOTFILES_DIR"

# Link only the config package here; the playbook's post-provision tasks link
# the rest. The playbook must be cloned first or its directory is not empty.
step "Playbook config"
if [[ ! -e $PLAYBOOK_DIR/config.yml ]]; then
  stow --no-folding --dir "$DOTFILES_DIR" --target "$HOME" "$CONFIG_PACKAGE"
fi
[[ -e $PLAYBOOK_DIR/config.yml ]] || die "no config.yml in $PLAYBOOK_DIR after stowing $CONFIG_PACKAGE."

step "Ansible requirements"
cd "$PLAYBOOK_DIR"
ansible-galaxy install -r requirements.yml

step "Playbook"
printf 'Sign in to the App Store app first if config.yml lists mas apps, or pass --skip-tags mas.\n'
read -r -p "Press Return to run the playbook. "
ansible-playbook main.yml "$@"
