import { Link } from 'react-router-dom'
import { CheckCircle2, Droplets, Eye, Leaf, Mountain, Thermometer, Waves } from 'lucide-react'
import heroImg from '@/assets/hero-cliff.png'

const stats = [
    { icon: Mountain, label: 'Cliff height', value: '14.5 m' },
    { icon: Waves, label: 'Water depth', value: '32 m' },
    { icon: Leaf, label: 'Water quality', value: 'Good' },
    { icon: Eye, label: 'Visibility', value: '18–30 m' },
    { icon: Thermometer, label: 'Sea temperature', value: '22.4 °C' },
    { icon: Droplets, label: 'Pollution level', value: 'Low' },
]

function SpotPreview() {
    return (
        <div className="rounded-2xl border border-white/10 bg-panel/90 p-5 shadow-2xl shadow-black/40 backdrop-blur sm:p-6">
            <div className="flex items-start justify-between gap-3">
                <div>
                    <p className="font-display text-xl font-bold">Blue Cliff Spot</p>
                    <span className="mt-2 inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-sm">
            <Mountain size={14} aria-hidden="true" /> Cliff Jumping
          </span>
                </div>
                <span className="rounded-full bg-white/10 px-2.5 py-1 text-xs text-white/70">
          Sample data
        </span>
            </div>

            <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-5 border-t border-white/10 pt-5">
                {stats.map(({ icon: Icon, label, value }) => (
                    <div key={label} className="flex items-center gap-3">
                        <Icon className="shrink-0 text-sky" size={28} aria-hidden="true" />
                        <div>
                            <dt className="text-sm text-white/65">{label}</dt>
                            <dd className="font-display text-lg font-bold">{value}</dd>
                        </div>
                    </div>
                ))}
            </dl>

            <div className="mt-5 flex items-start gap-3 rounded-xl border border-safe/50 bg-safe/10 p-4">
                <CheckCircle2 className="mt-0.5 shrink-0 text-safe" aria-hidden="true" />
                <div>
                    <p className="font-semibold">Suitable to jump</p>
                    <p className="text-sm text-white/75">
                        Cliff height is suitable, water is deep enough and pollution is low.
                    </p>
                </div>
            </div>
        </div>
    )
}

export default function Hero() {
    return (
        <section className="relative isolate overflow-hidden">
            <img src={heroImg} alt="" className="absolute inset-0 -z-20 h-full w-full object-cover" />
            <div className="absolute inset-0 -z-10 bg-night/75" />
            <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 py-16 sm:px-6 md:grid-cols-2 md:py-24">
                <div>
                    <h1 className="font-display text-4xl font-bold leading-tight sm:text-5xl lg:text-6xl">
                        Dive deeper.
                        <br />
                        Jump safer.
                    </h1>
                    <p className="mt-6 max-w-prose text-lg text-white/75">
                        Dive Spot Finder uses coastal mapping and satellite data to show where cliff jumping may be suitable, how clear the water is, and whether an oil spill has been detected nearby.
                    </p>
                    <div className="mt-8 flex flex-wrap gap-3">
                        <Link
                            to="/signup"
                            className="rounded-xl bg-sky px-6 py-3 font-semibold text-night hover:brightness-110"
                        >
                            Get Started
                        </Link>
                        <Link
                            to="/login"
                            className="rounded-xl border border-white/15 px-6 py-3 font-semibold hover:bg-white/10"
                        >
                            Sign In
                        </Link>
                    </div>
                </div>

                <SpotPreview />
            </div>
        </section>
    )
}