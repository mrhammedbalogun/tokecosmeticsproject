import type { components } from "@/lib/api-types";
import { fetchWithAuthOrBounce } from "@/lib/session";
import { ProfileForm } from "@/components/account/ProfileForm";
import { updateProfileAction } from "./actions";

type Me = components["schemas"]["Me"];

export default async function ProfilePage() {
  // This fetch is the page's gate; `/account/profile` is the literal current path
  // so an expired session bounces back HERE after renewal, not to the dashboard.
  const me = await fetchWithAuthOrBounce<Me>("/auth/me/", "/account/profile");

  return (
    <div>
      <h2 className="font-display text-2xl">Profile</h2>
      <div className="mt-6">
        <ProfileForm
          defaults={{
            email: me.email,
            first_name: me.first_name ?? "",
            last_name: me.last_name ?? "",
            phone: me.phone ?? "",
            whatsapp: me.whatsapp ?? "",
            marketing_consent: me.marketing_consent ?? false,
          }}
          action={updateProfileAction}
        />
      </div>
    </div>
  );
}
