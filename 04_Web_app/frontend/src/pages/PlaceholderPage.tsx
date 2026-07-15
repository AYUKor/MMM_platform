import { EmptyState } from "../shared/ui/EmptyState";

interface PlaceholderPageProps {
  title: string;
  description: string;
}

export function PlaceholderPage({ title, description }: PlaceholderPageProps) {
  return <EmptyState title={title} description={description} />;
}
