import type { Meta, StoryObj } from '@storybook/sveltekit';
import AgentSkillMatrixCard from './AgentSkillMatrixCard.svelte';

const meta = {
	title: 'Agents/Cards/SkillMatrix',
	component: AgentSkillMatrixCard,
	tags: ['autodocs'],
	args: {
		agent: {
			id: 'work',
			label: 'Work',
			description: 'Engineering execution',
			runtimeStatus: 'active'
		},
		groups: [
			{
				id: 'infrastructure',
				title: 'Infrastructure',
				skills: [
					{ id: 'docker', label: 'docker_cli', enabled: true },
					{ id: 'terraform', label: 'terraform_plan', enabled: false, missingDependency: true }
				]
			},
			{
				id: 'coding',
				title: 'Coding',
				skills: [
					{ id: 'bash', label: 'bash_exec', enabled: true },
					{ id: 'python', label: 'python_repl', enabled: true }
				]
			}
		]
	}
} satisfies Meta<typeof AgentSkillMatrixCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};
