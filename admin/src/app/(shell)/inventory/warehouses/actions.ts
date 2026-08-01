"use server";

/**
 * Saving a warehouse. Plan-17c Task 5.
 *
 * A SERVER FUNCTION, like every other authenticated write here.
 *
 * NO DELETE, and that is a refusal rather than an omission — `StockItem.warehouse` is
 * CASCADE, so deleting a warehouse would take every stock row it holds and strip the
 * context from every movement those rows recorded. Deactivating removes it from
 * `reserve()` and keeps the history, which is what "remove this warehouse" means when
 * somebody asks for it. `WarehouseAdminViewSet` answers 405 to DELETE for the same reason.
 *
 * THE COVERAGE CONFIRMATION IS THE CLIENT'S JOB, and deliberately so. The backend does not
 * refuse an edit that strands a market: reorganising warehouses is legitimate work and the
 * server cannot tell a mistake from step one of a two-step move. What it must not be is
 * quiet — so the screen names the consequence before it sends anything, computed from the
 * other warehouses (see `lib/warehouses.ts`).
 */
import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { fetchWithAuth } from "@/lib/session";

export interface WarehouseSaveState {
  savedAt?: number;
  fieldErrors?: Record<string, string>;
  message?: string | null;
}

export async function saveWarehouseAction(input: {
  id: number;
  name: string;
  location_country: string;
  serves_countries: string[];
  priority: number;
  is_active: boolean;
}): Promise<WarehouseSaveState> {
  if (!Number.isInteger(input.id) || input.id <= 0) {
    return { message: "That warehouse could not be identified." };
  }
  const name = input.name.trim();
  if (!name) return { fieldErrors: { name: "A warehouse needs a name." } };
  if (!Number.isInteger(input.priority) || input.priority < 0) {
    return { fieldErrors: { priority: "Priority is a whole number — lower is tried first." } };
  }

  try {
    await fetchWithAuth(`/admin/warehouses/${input.id}/`, {
      method: "PATCH",
      body: {
        name,
        location_country: input.location_country,
        serves_countries: input.serves_countries,
        priority: input.priority,
        is_active: input.is_active,
      },
    });
  } catch (e) {
    if (e instanceof ApiError) {
      const data = e.data as Record<string, unknown> | undefined;
      const fieldErrors: Record<string, string> = {};
      for (const key of ["name", "location_country", "serves_countries", "priority", "is_active"]) {
        const value = data?.[key];
        const first = Array.isArray(value) ? value[0] : value;
        if (typeof first === "string") fieldErrors[key] = first;
      }
      if (Object.keys(fieldErrors).length) return { fieldErrors };
      return { message: "That warehouse could not be saved." };
    }
    return { message: "The API is not responding." };
  }

  // Both matter: the grid's columns come from the active warehouses, and the manager
  // reads its own list back.
  revalidatePath("/inventory/warehouses");
  revalidatePath("/inventory");
  return { savedAt: Date.now() };
}
