alias gemini='agy'  # Gemini CLI migrated to Antigravity (agy)

# Agent harness launchers run under the mise "agent" env so gh/GitHub actions
# carry the agent machine-user identity (GH_TOKEN from config.agent.toml).
# mise exec resolves the trailing binary via PATH — no alias recursion.
# (claude sets MISE_ENV=agent via its settings env; gemini chains through agy.)
alias agy='mise x -E agent -- agy'
alias codex='mise x -E agent -- codex'
alias pi='mise x -E agent -- pi'

alias starwars="telnet towel.blinkenlights.nl"

alias sitenamr="grep '^[a-z].*[^aeiou]er$' /usr/share/dict/words | shuf -n 1 | sed -r -e 's/er$/r/' -e 's/^(\w)/\1/'"
alias sitenamd="grep '^[a-z].*[^aeiou]ed$' /usr/share/dict/words | shuf -n 1 | sed -r -e 's/ed$/d/' -e 's/^(\w)/\1/'"

# IP addresses
function hax {
	msg=$1
	#let lnstr=$(expr length "$msg")-1
	let lnstr=$(echo -n "$msg" | wc -c | tr -d ' ')-1
	for ((i = 0; i <= $lnstr; i++)); do
		echo -n "${msg:$i:1}"
		sleep .1
	done
	echo
}

function eipcore {
	extip1="$(curl -s icanhazip.com)"
	if [[ -z $extip1 ]]; then
		echo "Unavailable"
	else
		echo "$extip1"
	fi
}

function iipcore {
	intip1="$(/sbin/ifconfig | grep 'inet ' | awk '{ print $2; }' | grep -Fv 127.0.0.1)"
	if [[ -z $intip1 ]]; then
		echo "Unavailable"
	else
		echo "$intip1"
	fi
}

function eip {
	hax "$(eipcore)"
}

function iip {
	hax "$(iipcore)"
}

function aip {
	intip="$(iipcore)"
	extip="$(eipcore)"
	hax "Internal IP: ${intip}, External IP: $extip"
}
