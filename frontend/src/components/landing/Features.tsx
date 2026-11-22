import { Droplets, Mountain, Satellite } from 'lucide-react'

const features = [
    {
        icon: Mountain,
        title: 'Cliff jumping spots',
        text: 'Browse jumping locations on a map, with estimated cliff height, water depth and a suitability score for each one.',
    },
    {
        icon: Droplets,
        title: 'Water quality',
        text: 'Follow turbidity, chlorophyll-a and suspended particles to see how clear the water is before you go.',
    },
    {
        icon: Satellite,
        title: 'Oil spill detection',
        text: 'Satellite radar images help flag possible oil slicks near the coast, so you can avoid affected areas.',
    },
]

export default function Features() {
    return (
        <section id="features" className="scroll-mt-16">
            <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6 md:py-24">
                <h2 className="font-display text-3xl font-bold">What you can do</h2>

                <div className="mt-10 grid gap-5 md:grid-cols-3">
                    {features.map(({ icon: Icon, title, text }) => (
                        <article
                            key={title}
                            className="rounded-2xl border border-white/10 bg-panel p-6"
                        >
                            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-sky/15 text-sky">
                                <Icon size={26} aria-hidden="true" />
                            </div>
                            <h3 className="mt-5 font-display text-xl font-bold">{title}</h3>
                            <p className="mt-2 text-white/75">{text}</p>
                        </article>
                    ))}
                </div>
            </div>
        </section>
    )
}