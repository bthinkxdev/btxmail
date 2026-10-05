import { Link } from "react-router-dom";

import { PageHead } from "../components/ui";

export default function NotFound() {
  return (
    <>
      <PageHead title="Page not found" intro="The address may be mistyped, or the item was deleted." />
      <Link className="btn primary" to="/">Go to overview</Link>
    </>
  );
}
