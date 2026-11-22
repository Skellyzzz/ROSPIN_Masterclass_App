export default function About() {
    return (
        <section id="about" className="scroll-mt-16 border-y border-white/10 bg-panel/50">
            <div className="mx-auto grid max-w-6xl gap-6 px-4 py-16 sm:px-6 md:grid-cols-2 md:gap-12 md:py-24">
                <h2 className="font-display text-3xl font-bold">
                    Plan with real data, then check in person
                </h2>
                <div className="max-w-prose space-y-4 text-white/75">
                    <p>
                        Dive Spot Finder brings location data and satellite observations of the coast together in one place, so you do not have to piece them together from different sources.
                    </p>
                    <p>
                        Every figure on the platform is an estimate. Use it to plan your trip, and always look at the spot yourself before you jump.
                    </p>
                </div>
            </div>
        </section>
    )
}