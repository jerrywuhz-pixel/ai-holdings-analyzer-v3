export default function Loading() {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: 6 }).map((_, index) => (
        <div key={index} className="h-32 animate-pulse rounded-2xl border border-white/8 bg-white/[0.04]" />
      ))}
    </div>
  );
}
