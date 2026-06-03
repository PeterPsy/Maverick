import type { ReactNode, Dispatch, SetStateAction } from "react"
import { Filter, RefreshCw, Search, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuCheckboxItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import type { CalendarAccount } from "./calendar-types"

export function FilterBar(props: {
  searchQuery: string
  setSearchQuery: (value: string) => void
  colors: { name: string; value: string; bg: string; text: string }[]
  categories: string[]
  availableTags: string[]
  accountOptions: CalendarAccount[]
  selectedColors: string[]
  selectedTags: string[]
  selectedCategories: string[]
  selectedAccounts: string[]
  onSyncConnections?: () => void | Promise<void>
  isSyncingConnections?: boolean
  setSelectedColors: Dispatch<SetStateAction<string[]>>
  setSelectedTags: Dispatch<SetStateAction<string[]>>
  setSelectedCategories: Dispatch<SetStateAction<string[]>>
  setSelectedAccounts: Dispatch<SetStateAction<string[]>>
  hasActiveFilters: boolean
  clearFilters: () => void
  getColorClasses: (color: string) => { name?: string; bg: string; text: string }
  showSearch?: boolean
  showAccountFilters?: boolean
}) {
  const showAccountFilters = props.showAccountFilters !== false
  return (
    <div className="flex flex-col gap-2">
      {props.showSearch !== false && (
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input placeholder="Search events..." value={props.searchQuery} onChange={(event) => props.setSearchQuery(event.target.value)} className="pl-9" />
          {props.searchQuery && (
            <Button variant="ghost" size="icon" className="absolute right-1 top-1/2 h-7 w-7 -translate-y-1/2" onClick={() => props.setSearchQuery("")}>
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>
      )}

      <div className="sm:hidden">
        <div className="flex items-center justify-end">
          <MobileFiltersMenu {...props} showAccountFilters={showAccountFilters} />
          {showAccountFilters && (
            <FilterMenu title="Accounts" count={props.selectedAccounts.length} align="start" mobile>
              {props.accountOptions.map((account) => (
                <DropdownMenuCheckboxItem
                  key={account.value}
                  checked={props.selectedAccounts.includes(account.value)}
                  onCheckedChange={(checked) =>
                    props.setSelectedAccounts((prev) => checked ? [...prev, account.value] : prev.filter((item) => item !== account.value))
                  }
                >
                  {account.name}
                </DropdownMenuCheckboxItem>
              ))}
            </FilterMenu>
          )}
          {showAccountFilters && props.onSyncConnections && props.accountOptions.some((account) => account.provider === "google" && account.status === "connected") && (
            <Button
              variant="outline"
              size="sm"
              onClick={props.onSyncConnections}
              disabled={props.isSyncingConnections}
              className="gap-2 whitespace-nowrap flex-shrink-0"
            >
              <RefreshCw className={cn("h-4 w-4", props.isSyncingConnections && "animate-spin")} />
              Sync
            </Button>
          )}
        </div>
      </div>

      <div className="hidden sm:flex items-center gap-2">
        <FilterMenu title="Colors" count={props.selectedColors.length}>
          {props.colors.map((color) => (
            <DropdownMenuCheckboxItem
              key={color.value}
              checked={props.selectedColors.includes(color.value)}
              onCheckedChange={(checked) =>
                props.setSelectedColors((prev) => checked ? [...prev, color.value] : prev.filter((item) => item !== color.value))
              }
            >
              <div className="flex items-center gap-2">
                <div className={cn("h-3 w-3 rounded", color.bg)} />
                {color.name}
              </div>
            </DropdownMenuCheckboxItem>
          ))}
        </FilterMenu>
        <FilterMenu title="Tags" count={props.selectedTags.length}>
          {props.availableTags.map((tag) => (
            <DropdownMenuCheckboxItem
              key={tag}
              checked={props.selectedTags.includes(tag)}
              onCheckedChange={(checked) => props.setSelectedTags((prev) => checked ? [...prev, tag] : prev.filter((item) => item !== tag))}
            >
              {tag}
            </DropdownMenuCheckboxItem>
          ))}
        </FilterMenu>
        <FilterMenu title="Categories" count={props.selectedCategories.length}>
          {props.categories.map((category) => (
            <DropdownMenuCheckboxItem
              key={category}
              checked={props.selectedCategories.includes(category)}
              onCheckedChange={(checked) =>
                props.setSelectedCategories((prev) => checked ? [...prev, category] : prev.filter((item) => item !== category))
              }
            >
              {category}
            </DropdownMenuCheckboxItem>
          ))}
        </FilterMenu>
        {showAccountFilters && (
          <FilterMenu title="Accounts" count={props.selectedAccounts.length}>
            {props.accountOptions.map((account) => (
              <DropdownMenuCheckboxItem
                key={account.value}
                checked={props.selectedAccounts.includes(account.value)}
                onCheckedChange={(checked) =>
                  props.setSelectedAccounts((prev) => checked ? [...prev, account.value] : prev.filter((item) => item !== account.value))
                }
              >
                {account.name}
              </DropdownMenuCheckboxItem>
            ))}
          </FilterMenu>
        )}
        {showAccountFilters && props.onSyncConnections && props.accountOptions.some((account) => account.provider === "google" && account.status === "connected") && (
          <Button variant="outline" size="sm" onClick={props.onSyncConnections} disabled={props.isSyncingConnections} className="gap-2">
            <RefreshCw className={cn("h-4 w-4", props.isSyncingConnections && "animate-spin")} />
            {props.isSyncingConnections ? "Syncing" : "Sync"}
          </Button>
        )}
        {props.hasActiveFilters && (
          <Button variant="ghost" size="sm" onClick={props.clearFilters} className="gap-2">
            <X className="h-4 w-4" />
            Clear
          </Button>
        )}
      </div>
      {props.hasActiveFilters && (
        <div className="hidden flex-wrap items-center gap-2 sm:flex">
          <span className="text-sm text-muted-foreground">Active filters:</span>
          {props.selectedColors.map((colorValue) => {
            const color = props.getColorClasses(colorValue)
            return (
              <Badge key={colorValue} variant="secondary" className="gap-1">
                <div className={cn("h-2 w-2 rounded-full", color.bg)} />
                {color.name || colorValue}
                <button onClick={() => props.setSelectedColors((prev) => prev.filter((item) => item !== colorValue))} className="ml-1 hover:text-foreground">
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            )
          })}
          {props.selectedTags.map((tag) => (
            <Badge key={tag} variant="secondary" className="gap-1">
              {tag}
              <button onClick={() => props.setSelectedTags((prev) => prev.filter((item) => item !== tag))} className="ml-1 hover:text-foreground">
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
          {props.selectedCategories.map((category) => (
            <Badge key={category} variant="secondary" className="gap-1">
              {category}
              <button onClick={() => props.setSelectedCategories((prev) => prev.filter((item) => item !== category))} className="ml-1 hover:text-foreground">
                <X className="h-3 w-3" />
              </button>
            </Badge>
          ))}
          {props.selectedAccounts.map((accountValue) => {
            const account = props.accountOptions.find((item) => item.value === accountValue)
            return (
              <Badge key={accountValue} variant="secondary" className="gap-1">
                {account?.name || accountValue}
                <button onClick={() => props.setSelectedAccounts((prev) => prev.filter((item) => item !== accountValue))} className="ml-1 hover:text-foreground">
                  <X className="h-3 w-3" />
                </button>
              </Badge>
            )
          })}
        </div>
      )}
    </div>
  )
}

function MobileFiltersMenu(
  props: Omit<Parameters<typeof FilterBar>[0], "showSearch" | "showAccountFilters"> & { showAccountFilters: boolean },
) {
  const activeFilterCount = props.selectedColors.length + props.selectedTags.length + props.selectedCategories.length
  return (
    <DropdownMenu modal>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className="gap-2 whitespace-nowrap bg-transparent">
          <Filter className="h-4 w-4" />
          Filters
          {activeFilterCount > 0 && <Badge variant="secondary" className="ml-1 h-5 px-1.5">{activeFilterCount}</Badge>}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-[70vh] w-[min(calc(100vw-2rem),22rem)] overflow-y-auto">
        <DropdownMenuLabel>Colors</DropdownMenuLabel>
        {props.colors.map((color) => (
          <DropdownMenuCheckboxItem
            key={color.value}
            checked={props.selectedColors.includes(color.value)}
            onCheckedChange={(checked) =>
              props.setSelectedColors((prev) => checked ? [...prev, color.value] : prev.filter((item) => item !== color.value))
            }
          >
            <div className="flex items-center gap-2">
              <div className={cn("h-3 w-3 rounded", color.bg)} />
              {color.name}
            </div>
          </DropdownMenuCheckboxItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuLabel>Tags</DropdownMenuLabel>
        {props.availableTags.map((tag) => (
          <DropdownMenuCheckboxItem
            key={tag}
            checked={props.selectedTags.includes(tag)}
            onCheckedChange={(checked) => props.setSelectedTags((prev) => checked ? [...prev, tag] : prev.filter((item) => item !== tag))}
          >
            {tag}
          </DropdownMenuCheckboxItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuLabel>Categories</DropdownMenuLabel>
        {props.categories.map((category) => (
          <DropdownMenuCheckboxItem
            key={category}
            checked={props.selectedCategories.includes(category)}
            onCheckedChange={(checked) =>
              props.setSelectedCategories((prev) => checked ? [...prev, category] : prev.filter((item) => item !== category))
            }
          >
            {category}
          </DropdownMenuCheckboxItem>
        ))}
        {props.hasActiveFilters && (
          <>
            <DropdownMenuSeparator />
            <Button variant="ghost" size="sm" onClick={props.clearFilters} className="w-full justify-start gap-2">
              <X className="h-4 w-4" />
              Clear filters
            </Button>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function FilterMenu({
  title,
  count,
  children,
  align = "end",
  mobile = false,
}: {
  title: string
  count: number
  children: ReactNode
  align?: "start" | "end"
  mobile?: boolean
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="sm" className={cn("gap-2 bg-transparent", mobile && "whitespace-nowrap flex-shrink-0")}>
          <Filter className="h-4 w-4" />
          {title}
          {count > 0 && <Badge variant="secondary" className={cn("ml-1 h-5", mobile ? "px-1.5" : "px-1")}>{count}</Badge>}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align={align} className="w-48">
        <DropdownMenuLabel>Filter by {filterLabel(title)}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {children}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function filterLabel(title: string) {
  if (title === "Colors") return "Color"
  if (title === "Tags") return "Tag"
  if (title === "Accounts") return "Calendar Account"
  return "Category"
}
