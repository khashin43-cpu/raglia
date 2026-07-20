<script lang="ts">
	import { getContext } from 'svelte';
	import { models, type Model } from '$lib/stores';
	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import Check from '$lib/components/icons/Check.svelte';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import UserGroup from '$lib/components/icons/UserGroup.svelte';

	const i18n = getContext<any>('i18n');

	export let selectedModels: string[] = [''];
	export let disabled = false;
	export let onAgentSelect: (model: Model) => void = () => {};

	const sipPrefix = 'agent:sip:';
	const sipConsultantId = `${sipPrefix}chat_lnd`;
	const sipConsultantName = 'Консультант по ЛНАД';

	let showAgents = false;
	let searchValue = '';

	const isSipModel = (model: Model | null | undefined) =>
		model?.agent?.provider === 'sip' || model?.id?.startsWith(sipPrefix);
	const isUserAgent = (model: Model | null | undefined) =>
		model?.agent?.provider === 'ragflow' || (model?.info?.meta as any)?.agent_group === 'user';
	const normalizedAgentId = (model: Model) => (isSipModel(model) ? sipConsultantId : model.id);
	const agentName = (model: Model | null | undefined) =>
		model?.agent?.name || model?.name || model?.id || $i18n.t('Agent');
	const agentDescription = (model: Model | null | undefined) =>
		model?.info?.meta?.description || model?.agent?.description || model?.id || '';
	const assistantCountLabel = (count: number) => {
		const lastDigit = count % 10;
		const lastTwoDigits = count % 100;
		if (lastDigit === 1 && lastTwoDigits !== 11) return 'ассистент';
		if (lastDigit >= 2 && lastDigit <= 4 && (lastTwoDigits < 12 || lastTwoDigits > 14)) {
			return 'ассистента';
		}
		return 'ассистентов';
	};

	const buildAgentGroups = (availableModels: Model[]) => {
		const system: Model[] = [];
		const user: Model[] = [];
		let sipItem: Model | null = null;

		for (const model of availableModels ?? []) {
			if (model?.info?.meta?.hidden) continue;
			if (model?.owned_by !== 'agent' && !model?.info?.meta?.agent) continue;
			if (isSipModel(model)) {
				if (!sipItem || model.id === selectedModels?.[0]) sipItem = model;
				continue;
			}
			const group = (model?.info?.meta as any)?.agent_group;
			if (group === 'user' || model?.agent?.provider === 'ragflow') user.push(model);
			else system.push(model);
		}

		if (sipItem) system.push(sipItem);
		return { system, user };
	};

	$: selectedModelId = selectedModels?.[0] || '';
	$: selectedModel = ($models ?? []).find((model) => model.id === selectedModelId);
	$: selectedAgentModels = selectedModels
		.map((id) => ($models ?? []).find((model) => model.id === id))
		.filter((model): model is Model => Boolean(model));
	$: selectedUserAgents = selectedAgentModels.filter(isUserAgent);
	$: selectedIsSip = isSipModel(selectedModel) || selectedModelId.startsWith(sipPrefix);
	$: selectedLabel =
		selectedAgentModels.length > 1
			? `${selectedAgentModels.length} ${assistantCountLabel(selectedAgentModels.length)}`
			: selectedIsSip
				? sipConsultantName
				: selectedModel?.owned_by === 'agent'
					? agentName(selectedModel)
					: 'Ассистент';
	$: agentGroups = buildAgentGroups($models ?? []);
	$: matchesSearch = (model: Model) => {
		const query = searchValue.trim().toLowerCase();
		if (!query) return true;
		return `${agentName(model)} ${agentDescription(model)}`.toLowerCase().includes(query);
	};
	$: filteredAgentGroups = [
		{ id: 'system', label: 'Системные', items: agentGroups.system.filter(matchesSearch) },
		{ id: 'user', label: 'Пользовательские', items: agentGroups.user.filter(matchesSearch) }
	].filter((group) => group.items.length > 0);

	const selectAgent = (model: Model) => {
		if (disabled) return;

		const modelId = normalizedAgentId(model);
		if (isUserAgent(model)) {
			const selectedUserAgentIds = selectedModels.filter((id) => {
				const selectedAgent = ($models ?? []).find((item) => item.id === id);
				return isUserAgent(selectedAgent);
			});

			if (selectedUserAgentIds.includes(modelId)) {
				// В чате всегда должен оставаться хотя бы один выбранный ассистент.
				if (selectedUserAgentIds.length > 1) {
					selectedModels = selectedUserAgentIds.filter((id) => id !== modelId);
				}
			} else {
				selectedModels = [...selectedUserAgentIds, modelId];
			}
			onAgentSelect(model);
			return;
		}

		// Системные режимы взаимоисключающие и заменяют пользовательский набор.
		selectedModels = [modelId];
		onAgentSelect(model);
		showAgents = false;
	};
</script>

<div class="flex min-w-0 items-center gap-1">
	<Dropdown
		bind:show={showAgents}
		side="top"
		align="start"
		onOpenChange={(show) => {
			if (show) searchValue = '';
		}}
	>
		<button
			type="button"
			class="flex h-8 max-w-48 items-center gap-1.5 rounded-full px-2.5 text-sm text-gray-700 transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-60 dark:text-gray-200 dark:hover:bg-gray-800"
			{disabled}
			aria-label={$i18n.t('Select an agent')}
		>
			<UserGroup className="size-4 shrink-0" strokeWidth="1.8" />
			<span class="truncate">{selectedLabel}</span>
			<ChevronDown className="size-3 shrink-0" strokeWidth="2.2" />
		</button>

		<div slot="content">
			<div
				class="w-[min(22rem,calc(100vw-2rem))] rounded-2xl border border-gray-100 bg-white p-1 shadow-lg dark:border-gray-800 dark:bg-gray-850 dark:text-white"
			>
				<div class="relative m-1 mb-2">
					<Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-gray-400" />
					<input
						class="w-full rounded-xl bg-gray-50 py-2 pl-8 pr-3 text-sm outline-none placeholder:text-gray-400 focus:ring-1 focus:ring-gray-300 dark:bg-gray-900 dark:focus:ring-gray-700"
						type="search"
						placeholder="Поиск ассистентов"
						bind:value={searchValue}
					/>
				</div>
				{#if agentGroups.user.length > 0}
					<div class="px-3 pb-1 text-xs text-gray-500 dark:text-gray-400">
						Пользовательских ассистентов можно выбрать несколько
					</div>
				{/if}

				<div class="max-h-72 overflow-y-auto scrollbar-thin">
					{#if filteredAgentGroups.length === 0}
						<div class="px-3 py-6 text-center text-sm text-gray-500">Ассистенты не найдены</div>
					{:else}
						{#each filteredAgentGroups as group (group.id)}
							<div
								class="px-3 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wide text-gray-400"
							>
								{group.label}
							</div>
							{#each group.items as model (model.id)}
								{@const itemIsSip = isSipModel(model)}
								{@const itemSelected = selectedModels.includes(normalizedAgentId(model))}
								<button
									type="button"
									class="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm transition hover:bg-gray-50 dark:hover:bg-gray-800/60"
									on:click={() => selectAgent(model)}
								>
									<div
										class="flex size-8 shrink-0 items-center justify-center rounded-full bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-200"
									>
										{itemIsSip ? 'Л' : agentName(model).slice(0, 1).toUpperCase()}
									</div>
									<div class="min-w-0 flex-1">
										<div class="truncate font-medium">
											{itemIsSip ? sipConsultantName : agentName(model)}
										</div>
										<div class="truncate text-xs text-gray-500 dark:text-gray-400">
											{itemIsSip
												? 'Консультации по локально-нормативной документации'
												: agentDescription(model)}
										</div>
									</div>
									{#if itemSelected}<Check className="size-4 shrink-0" />{/if}
								</button>
							{/each}
						{/each}
					{/if}
				</div>

				{#if selectedUserAgents.length > 0}
					<div
						class="mt-1 flex items-center justify-between border-t border-gray-100 px-3 py-2 dark:border-gray-800"
					>
						<span class="text-xs text-gray-500 dark:text-gray-400">
							Выбрано: {selectedUserAgents.length}
						</span>
						<button
							type="button"
							class="rounded-lg bg-gray-900 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-gray-700 dark:bg-white dark:text-gray-900 dark:hover:bg-gray-200"
							on:click={() => (showAgents = false)}
						>
							Готово
						</button>
					</div>
				{/if}
			</div>
		</div>
	</Dropdown>
</div>
