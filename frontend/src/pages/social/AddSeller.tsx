import { useState } from "react";
import { Button, Field, Input, Modal, Msg, Notice, Select, Textarea } from "../../components/ui";
import { api } from "../../lib/api";
import { useAction } from "../../lib/hooks";
import { CATEGORY, type SellerDetail } from "../../lib/social";

/** Add one seller from a public link. The source that always works, with or without a search API. */
export function AddSellerModal({ open, onClose, onAdded }:
{ open: boolean; onClose: () => void; onAdded: (id: number) => void }) {
  const [f, setF] = useState({
    link: "", name: "", description: "", category: "", address: "", delivery_area: "",
    website: "", phone: "", email: "", note: "", source_url: "",
  });
  const { busy, msg, run, setMsg } = useAction();
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  const submit = async () => {
    const body = Object.fromEntries(Object.entries(f).filter(([, v]) => v.trim()));
    const r = await run(() => api.post<{ outcome: string; seller: SellerDetail; reason?: string }>("/social/sellers", body));
    if (!r) return;
    if (r.outcome === "duplicate") { setMsg({ kind: "err", text: `Already tracked: ${r.reason ?? "duplicate"}` }); return; }
    setF({ link: "", name: "", description: "", category: "", address: "", delivery_area: "", website: "", phone: "", email: "", note: "", source_url: "" });
    onAdded(r.seller.id);
  };

  return (
    <Modal open={open} onClose={onClose} title="Add a business or profile"
      footer={<>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="primary" loading={busy} disabled={!f.link.trim()} onClick={submit}>Add seller</Button>
      </>}>
      <div className="space-y-3">
        <Field label="Public link or handle"
          hint="An Instagram or Facebook business profile, a WhatsApp business number, a catalogue link or their website.">
          <Input value={f.link} onChange={set("link")} autoFocus
            placeholder="https://www.instagram.com/theirhandle/  ·  @theirhandle  ·  9876543210" />
        </Field>
        <Notice kind="info">
          A post or reel link will not work — use the profile link. IOI never opens DMs, chats, groups or follower
          lists, and it cannot read Instagram or Facebook profile pages automatically: you open those and record what
          you saw.
        </Notice>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Business name" hint="Leave blank to use their handle."><Input value={f.name} onChange={set("name")} placeholder="Asha Cakes" /></Field>
          <Field label="What they sell">
            <Select value={f.category} onChange={set("category")}>
              <option value="">Work it out from their own words</option>
              {Object.entries(CATEGORY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
          </Field>
        </div>
        <Field label="Their own description" hint="Paste their bio or catalogue text. IOI reads order complexity out of it.">
          <Textarea rows={3} value={f.description} onChange={set("description")}
            placeholder="Custom cakes and brownies. 50% advance to confirm. Order 3 days in advance. Delivery across Chennai." />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Address they publish" hint="Only what the business itself states.">
            <Input value={f.address} onChange={set("address")} placeholder="Adyar, Chennai 600020" />
          </Field>
          <Field label="Delivery or service area they publish">
            <Input value={f.delivery_area} onChange={set("delivery_area")} placeholder="Delivers across Velachery, Chennai" />
          </Field>
          <Field label="Website or catalogue"><Input value={f.website} onChange={set("website")} placeholder="https://…" /></Field>
          <Field label="Business phone"><Input value={f.phone} onChange={set("phone")} placeholder="9876543210" /></Field>
          <Field label="Business email"><Input value={f.email} onChange={set("email")} placeholder="hello@…" /></Field>
          <Field label="Where you found them" hint="Optional. Defaults to the link above.">
            <Input value={f.source_url} onChange={set("source_url")} placeholder="https://…" />
          </Field>
        </div>
        <Field label="Your note"><Textarea rows={2} value={f.note} onChange={set("note")} /></Field>
        <Msg msg={msg} />
      </div>
    </Modal>
  );
}
