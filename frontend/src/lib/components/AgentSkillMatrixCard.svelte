<script lang="ts">
	import type { AgentInfo } from '$lib/types';
	import type { AgentProfile } from '$lib/api/agents';

	export interface SkillCell {
		id: string;
		label: string;
		enabled: boolean;
		missingDependency?: boolean;
	}

	export interface SkillGroup {
		id: string;
		title: string;
		skills: SkillCell[];
	}

	interface Props {
		agent: AgentInfo;
		profile?: AgentProfile | null;
		groups?: SkillGroup[];
	}

	let { agent, profile = null, groups = [] }: Props = $props();

	const computedGroups = $derived.by<SkillGroup[]>(() => {
		if (groups.length > 0) return groups;
		const builtin = (profile?.builtinTools ?? []).map((tool) => ({
			id: `builtin:${tool}`,
			label: tool,
			enabled: true
		}));
		const modules = Object.keys(profile?.moduleConfig ?? {}).map((moduleName) => ({
			id: `module:${moduleName}`,
			label: moduleName,
			enabled: true
		}));
		if (builtin.length === 0 && modules.length === 0) {
			return [
				{
					id: 'none',
					title: 'Capabilities',
					skills: [{ id: 'none', label: 'No runtime skills exposed', enabled: false }]
				}
			];
		}
		return [
			{ id: 'builtin', title: 'Builtin Tools', skills: builtin },
			{ id: 'modules', title: 'Modules', skills: modules }
		].filter((group) => group.skills.length > 0);
	});
</script>

<section class="rounded border border-border-muted bg-surface p-3">
	<h4 class="text-xs uppercase tracking-wide text-text-muted">Skill Matrix</h4>
	<p class="mt-1 text-xs text-text-secondary">Capability map for {agent.id}</p>

	<div class="mt-2 space-y-2">
		{#each computedGroups as group (group.id)}
			<div class="rounded border border-border-muted bg-inset px-2 py-2">
				<p class="text-[11px] font-medium text-text-primary">{group.title}</p>
				<div class="mt-2 grid gap-1 sm:grid-cols-2">
					{#each group.skills as skill (skill.id)}
						<div class="flex items-center justify-between rounded border border-border-muted bg-surface px-2 py-1">
							<div class="flex items-center gap-2">
								<input type="checkbox" class="h-3 w-3" checked={skill.enabled} disabled />
								<span class="text-xs text-text-secondary">{skill.label}</span>
							</div>
							{#if skill.missingDependency}
								<span class="text-[10px] text-warning">missing dep</span>
							{/if}
						</div>
					{/each}
				</div>
			</div>
		{/each}
	</div>
</section>
