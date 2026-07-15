import { redirect } from "next/navigation";

/** Multi-route monitor retired — everything is on the single home page. */
export default function MonitorPage() {
  redirect("/");
}
