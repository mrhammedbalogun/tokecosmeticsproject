import { requireAuth } from "@/lib/session";
import { PasswordChangeForm } from "@/components/account/PasswordChangeForm";
import { DeleteAccountForm } from "@/components/account/DeleteAccountForm";
import { changePasswordAction, deleteAccountAction } from "./actions";

export default async function SecurityPage() {
  // This page renders no upstream data, so requireAuth IS its gate — same decision
  // function as the fetching pages, minus a fetch it has no use for.
  await requireAuth("/account/security");

  return (
    <div>
      <h2 className="font-display text-2xl">Security</h2>

      <section className="mt-6">
        <h3 className="font-medium">Change password</h3>
        <div className="mt-3">
          <PasswordChangeForm action={changePasswordAction} />
        </div>
      </section>

      <section className="mt-10 border-t border-line pt-6">
        <h3 className="font-medium text-red-700">Danger zone</h3>
        <div className="mt-3">
          <DeleteAccountForm action={deleteAccountAction} />
        </div>
      </section>
    </div>
  );
}
