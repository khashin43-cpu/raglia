<script lang="ts">
	import { toast } from 'svelte-sonner';

	import {
		getKnowledgeSpaces,
		uploadKnowledgeDocuments,
		type KnowledgeDataset,
		type KnowledgeSpace
	} from '$lib/apis/ragflow';
	import { removeAllDetails } from '$lib/utils';
	import Modal from '$lib/components/common/Modal.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Database from '$lib/components/icons/Database.svelte';
	import { getOutputText } from '../Messages/structuredOutput';

	export let show = false;
	export let title = '';
	export let messages: any[] = [];

	let spaces: KnowledgeSpace[] = [];
	let datasets: KnowledgeDataset[] = [];
	let selectedSpaceId = '';
	let selectedDatasetId = '';
	let loading = false;
	let saving = false;
	let wasOpen = false;

	$: selectedSpace = spaces.find((space) => space.id === selectedSpaceId) ?? null;
	$: datasets = selectedSpace?.datasets ?? [];
	$: if (selectedSpaceId && !datasets.some((dataset) => dataset.id === selectedDatasetId)) {
		selectedDatasetId = datasets[0]?.id ?? '';
	}

	$: if (show && !wasOpen) {
		wasOpen = true;
		void loadSpaces();
	} else if (!show) {
		wasOpen = false;
	}

	const errorMessage = (error: unknown) =>
		error instanceof Error
			? error.message
			: typeof error === 'string'
				? error
				: 'Неизвестная ошибка';

	const loadSpaces = async () => {
		loading = true;
		try {
			spaces = await getKnowledgeSpaces(localStorage.token);
			if (!spaces.some((space) => space.id === selectedSpaceId)) {
				selectedSpaceId = spaces[0]?.id ?? '';
			}
			const selected = spaces.find((space) => space.id === selectedSpaceId);
			if (!selected?.datasets?.some((dataset) => dataset.id === selectedDatasetId)) {
				selectedDatasetId = selected?.datasets?.[0]?.id ?? '';
			}
		} catch (error) {
			spaces = [];
			selectedSpaceId = '';
			selectedDatasetId = '';
			toast.error(`Не удалось загрузить пространства: ${errorMessage(error)}`);
		} finally {
			loading = false;
		}
	};

	const contentToText = (message: any) => {
		const outputText = getOutputText(message?.output);
		const content = outputText || message?.content || '';
		if (typeof content === 'string') return removeAllDetails(content).trim();
		if (Array.isArray(content)) {
			return content
				.map((part) => {
					if (typeof part === 'string') return part;
					if (part?.type === 'text') return part.text ?? '';
					return '';
				})
				.filter(Boolean)
				.join('\n\n')
				.trim();
		}
		return String(content).trim();
	};

	const resolveTitle = () => {
		const firstQuestion = messages.find((message) => message?.role === 'user');
		const fallback = contentToText(firstQuestion).split('\n')[0].trim();
		return title.trim() || fallback || 'История чата';
	};

	const buildMarkdown = () => {
		const savedAt = new Date();
		const roleNames: Record<string, string> = {
			user: 'Пользователь',
			assistant: 'Ассистент',
			system: 'Системная инструкция'
		};
		const sections = messages
			.map((message) => {
				const content = contentToText(message);
				if (!content) return '';
				const role = roleNames[message?.role] ?? 'Сообщение';
				const fileNames = (message?.files ?? [])
					.map((file) => file?.name)
					.filter(Boolean)
					.map((name) => `- ${name}`)
					.join('\n');
				return `## ${role}\n\n${content}${fileNames ? `\n\n**Вложения:**\n${fileNames}` : ''}`;
			})
			.filter(Boolean)
			.join('\n\n---\n\n');

		return [
			`# ${resolveTitle()}`,
			'',
			`- Сохранено из ЛИА: ${savedAt.toLocaleString('ru-RU')}`,
			`- Сообщений: ${messages.length}`,
			'',
			'---',
			'',
			sections
		].join('\n');
	};

	const fileName = () => {
		const safeTitle = resolveTitle()
			.replace(/[\\/:*?"<>|]+/g, '_')
			.replace(/\s+/g, ' ')
			.trim()
			.slice(0, 80);
		const date = new Date().toISOString().slice(0, 10);
		return `${safeTitle || 'История чата'} — ${date}.md`;
	};

	const save = async () => {
		if (!selectedDatasetId) {
			toast.error('Выберите базу знаний');
			return;
		}
		if (!messages.length) {
			toast.error('В чате пока нет сообщений');
			return;
		}

		saving = true;
		try {
			const markdown = buildMarkdown();
			const file = new File([markdown], fileName(), {
				type: 'text/markdown;charset=utf-8'
			});
			await uploadKnowledgeDocuments(localStorage.token, selectedDatasetId, [file]);
			toast.success('История чата сохранена в базе знаний. RAGFlow начал обработку документа.');
			show = false;
		} catch (error) {
			toast.error(`Не удалось сохранить историю чата: ${errorMessage(error)}`);
		} finally {
			saving = false;
		}
	};
</script>

<Modal bind:show size="sm">
	<div class="p-6">
		<div class="flex items-start gap-3">
			<div
				class="flex size-10 shrink-0 items-center justify-center rounded-xl bg-gray-100 text-gray-600 dark:bg-gray-850 dark:text-gray-300"
			>
				<Database className="size-5" />
			</div>
			<div>
				<h2 class="text-xl font-semibold">Сохранить историю чата в базу</h2>
				<p class="mt-1 text-sm leading-5 text-gray-500">
					Диалог будет преобразован в Markdown и отправлен в RAGFlow 0.24 как документ.
				</p>
			</div>
		</div>

		{#if loading}
			<div class="flex min-h-40 items-center justify-center">
				<Spinner className="size-5" />
			</div>
		{:else if spaces.length === 0}
			<div
				class="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200"
			>
				Сначала создайте пространство и базу знаний во вкладке «Ассистенты по Вашим базам знаний».
			</div>
		{:else}
			<div class="mt-5 space-y-4">
				<label class="block">
					<span class="mb-1.5 block text-sm font-medium">Пространство</span>
					<select
						class="w-full rounded-xl border border-gray-200 bg-transparent px-3 py-2.5 text-sm outline-none dark:border-gray-700"
						bind:value={selectedSpaceId}
					>
						{#each spaces as space (space.id)}
							<option value={space.id}>{space.name}</option>
						{/each}
					</select>
				</label>

				<label class="block">
					<span class="mb-1.5 block text-sm font-medium">База знаний</span>
					<select
						class="w-full rounded-xl border border-gray-200 bg-transparent px-3 py-2.5 text-sm outline-none disabled:opacity-50 dark:border-gray-700"
						bind:value={selectedDatasetId}
						disabled={datasets.length === 0}
					>
						{#if datasets.length === 0}
							<option value="">В пространстве нет баз знаний</option>
						{:else}
							{#each datasets as dataset (dataset.id)}
								<option value={dataset.id}>{dataset.name}</option>
							{/each}
						{/if}
					</select>
				</label>

				<div class="rounded-xl bg-gray-50 px-4 py-3 text-xs text-gray-500 dark:bg-gray-950">
					<div class="truncate font-medium text-gray-700 dark:text-gray-300">{fileName()}</div>
					<div class="mt-1">{messages.length} сообщений · формат Markdown</div>
				</div>
			</div>
		{/if}

		<div class="mt-6 flex justify-end gap-2">
			<button
				type="button"
				class="rounded-full px-4 py-2 text-sm hover:bg-gray-100 dark:hover:bg-gray-800"
				on:click={() => (show = false)}
			>
				Отмена
			</button>
			<button
				type="button"
				class="rounded-full bg-gray-900 px-5 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-gray-900"
				disabled={loading || saving || !selectedDatasetId || messages.length === 0}
				on:click={save}
			>
				{saving ? 'Сохранение…' : 'Сохранить в базу'}
			</button>
		</div>
	</div>
</Modal>
