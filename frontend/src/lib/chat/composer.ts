export interface AgentMentionParseResult {
	message: string;
	targetAgent?: string;
	targetAgents?: string[];
}

export interface SlashCommand {
	command: string;
	args: string[];
	rawArgs: string;
}

export function parseAgentMention(
	input: string,
	isKnownAgent: (name: string) => boolean
): AgentMentionParseResult {
	const leftTrimmed = input.trimStart();

	// Escaped prefix: @@agent message -> literal @agent message.
	if (leftTrimmed.startsWith('@@')) {
		return { message: leftTrimmed.slice(1) };
	}

	const match = leftTrimmed.match(/^@([a-zA-Z0-9_-]+)\s+([\s\S]+)$/);
	if (!match) {
		return { message: input };
	}

	const candidate = match[1].toLowerCase();
	if (candidate === 'all') {
		return {
			message: match[2].trim(),
			targetAgents: ['@all']
		};
	}
	if (!isKnownAgent(candidate)) {
		return { message: input };
	}

	const body = match[2].trim();
	if (!body) {
		return { message: input };
	}

	return {
		message: body,
		targetAgent: candidate
	};
}

export function parseSlashCommand(input: string): SlashCommand | null {
	const leftTrimmed = input.trimStart();
	if (!leftTrimmed.startsWith('/')) {
		return null;
	}
	const parts = leftTrimmed.slice(1).split(/\s+/).filter(Boolean);
	if (parts.length === 0) {
		return null;
	}
	const [command, ...args] = parts;
	return {
		command: command.toLowerCase(),
		args,
		rawArgs: args.join(' ').trim()
	};
}
