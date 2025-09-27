/*
 * ISO-standard metric threads, following this specification:
 *          http://en.wikipedia.org/wiki/ISO_metric_screw_thread
 *
 * Copyright 2023 Dan Kirshner - dan_kirshner@yahoo.com
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * See <http://www.gnu.org/licenses/>.
 */

// Examples.
// Standard M8 x 1.
// metric_thread (diameter=8, pitch=1, length=4);

// Square thread.
// metric_thread (diameter=8, pitch=1, length=4, square=true);

// Non-standard: long pitch, same thread size.
// metric_thread (diameter=8, pitch=4, length=4, thread_size=1, groove=true);

// Non-standard: 20 mm diameter, long pitch, square "trough" width 3 mm,
// depth 1 mm.
// metric_thread (diameter=20, pitch=8, length=16, square=true, thread_size=6,
//               groove=true, rectangle=0.333);

// English: 1/4 x 20.
// english_thread (diameter=1/4, threads_per_inch=20, length=1);

// Tapered.  Example -- pipe size 3/4" -- per:
// http://www.engineeringtoolbox.com/npt-national-pipe-taper-threads-d_750.html
// english_thread (diameter=1.05, threads_per_inch=14, length=3/4, taper=1/16);

// Thread for mounting on Rohloff hub.
// difference () {
//    cylinder (r=20, h=10, $fn=100);
//    metric_thread (diameter=34, pitch=1, length=10, internal=true, n_starts=6);
// }

// ----------------------------------------------------------------------------
function segments (diameter) = min (100, max (ceil (diameter*4), 20));

// ----------------------------------------------------------------------------
module metric_thread (diameter=8, pitch=1, length=1, internal=false, n_starts=1,
                      thread_size=-1, groove=false, square=false, rectangle=0,
                      angle=30, taper=0, leadin=0, leadfac=1.0, test=false,
                      segments_override=-1)
{
   local_thread_size = thread_size == -1 ? pitch : thread_size;
   local_rectangle = rectangle ? rectangle : 1;

   n_segments = segments_override > 0 ? segments_override : segments (diameter);

   h = (test && ! internal) ? 0 : (square || rectangle) ? local_thread_size*local_rectangle/2 : local_thread_size / (2 * tan(angle));

   h_fac1 = (square || rectangle) ? 0.90 : 0.625;
   h_fac2 = (square || rectangle) ? 0.95 : 5.3/8;

   tapered_diameter = diameter - length*taper;

   difference () {
      union () {
         if (! groove) {
            if (! test) {
               metric_thread_turns (diameter, pitch, length, internal, n_starts,
                                    local_thread_size, groove, square, rectangle, angle,
                                    taper, n_segments);
            }
         }

         difference () {
            if (groove) {
               cylinder (r1=diameter/2, r2=tapered_diameter/2,
                         h=length, $fn=n_segments);
            } else if (internal) {
               cylinder (r1=diameter/2 - h*h_fac1, r2=tapered_diameter/2 - h*h_fac1,
                         h=length, $fn=n_segments);
            } else {
               cylinder (r1=diameter/2 - h*h_fac2, r2=tapered_diameter/2 - h*h_fac2,
                         h=length, $fn=n_segments);
            }

            if (groove) {
               if (! test) {
                  metric_thread_turns (diameter, pitch, length, internal, n_starts,
                                       local_thread_size, groove, square, rectangle,
                                       angle, taper, n_segments);
               }
            }
         }

         if (internal) {
            if (leadin == 2 || leadin == 3) {
               cylinder (r1=diameter/2 - h + h*h_fac1*leadfac,
                         r2=diameter/2 - h,
                         h=h*h_fac1*leadfac, $fn=n_segments);
            }

            if (leadin == 1 || leadin == 2) {
               translate ([0, 0, length + 0.05 - h*h_fac1*leadfac]) {
                  cylinder (r1=tapered_diameter/2 - h,
                            h=h*h_fac1*leadfac,
                            r2=tapered_diameter/2 - h + h*h_fac1*leadfac,
                            $fn=n_segments);
               }
            }
         }
      }

      if (! internal) {
         if (leadin == 2 || leadin == 3) {
            difference () {
               linear_extrude (h*h_fac1*leadfac) {
                  circle(r=diameter/2 + 1, $fn=n_segments);
               }
               cylinder (r2=diameter/2, r1=diameter/2 - h*h_fac1*leadfac, h=h*h_fac1*leadfac,
                         $fn=n_segments);
            }
         }

         if (leadin == 1 || leadin == 2) {
            translate ([0, 0, length + 0.05 - h*h_fac1*leadfac]) {
               difference () {
                  linear_extrude (h*h_fac1*leadfac) {
                     circle(r=diameter/2 + 1, $fn=n_segments);
                  }
                  cylinder (r1=tapered_diameter/2, r2=tapered_diameter/2 - h*h_fac1*leadfac, h=h*h_fac1*leadfac,
                            $fn=n_segments);
               }
            }
         }
      }
   }
}

// ----------------------------------------------------------------------------
module metric_thread_turns (diameter, pitch, length, internal, n_starts,
                            thread_size, groove, square, rectangle, angle,
                            taper, n_segments)
{
   n_turns = floor (length/pitch);

   intersection () {
      for (i=[-1*n_starts : n_turns+1]) {
         translate ([0, 0, i*pitch]) {
            metric_thread_turn (diameter, pitch, internal, n_starts,
                                thread_size, groove, square, rectangle, angle,
                                taper, i*pitch, n_segments);
         }
      }
      linear_extrude (length) {
         square (diameter*3, center=true);
      }
   }
}

// ----------------------------------------------------------------------------
module metric_thread_turn (diameter, pitch, internal, n_starts, thread_size,
                           groove, square, rectangle, angle, taper, z, n_segments)
{
   fraction_circle = 1.0/n_segments;
   for (i=[0 : n_segments-1]) {
      rotate ([0, 0, (i + 0.5)*360*fraction_circle + 90]) {
         translate ([0, 0, i*n_starts*pitch*fraction_circle]) {
            thread_polyhedron ((diameter - taper*(z + i*n_starts*pitch*fraction_circle))/2,
                               pitch, internal, n_starts, thread_size, groove,
                               square, rectangle, angle);
         }
      }
   }
}

// ----------------------------------------------------------------------------
module thread_polyhedron (radius, pitch, internal, n_starts, thread_size,
                          groove, square, rectangle, angle)
{
   n_segments = segments (radius*2);
   fraction_circle = 1.0/n_segments;

   local_rectangle = rectangle ? rectangle : 1;

   h = (square || rectangle) ? thread_size*local_rectangle/2 : thread_size / (2 * tan(angle));
   outer_r = radius + (internal ? h/20 : 0);
   h_fac1 = (square || rectangle) ? 1.1 : 0.875;
   inner_r = radius - h*h_fac1;

   translate_y = groove ? outer_r + inner_r : 0;
   reflect_x   = groove ? 1 : 0;

   x_incr_outer = (! groove ? outer_r : inner_r) * fraction_circle * 2 * PI * 1.02;
   x_incr_inner = (! groove ? inner_r : outer_r) * fraction_circle * 2 * PI * 1.02;
   z_incr = n_starts * pitch * fraction_circle * 1.005;

   x1_outer = outer_r * fraction_circle * 2 * PI;
   z0_outer = (outer_r - inner_r) * tan(angle);

   z1_outer = z0_outer + z_incr;

   bottom = internal ? 0.235 : 0.25;
   top    = internal ? 0.765 : 0.75;

   translate ([0, translate_y, 0]) {
      mirror ([reflect_x, 0, 0]) {
         if (square || rectangle) {
            polyhedron (
               points = [
                         [-x_incr_inner/2, -inner_r, bottom*thread_size],
                         [x_incr_inner/2, -inner_r, bottom*thread_size + z_incr],
                         [x_incr_inner/2, -inner_r, top*thread_size + z_incr],
                         [-x_incr_inner/2, -inner_r, top*thread_size],
                         [-x_incr_outer/2, -outer_r, bottom*thread_size],
                         [x_incr_outer/2, -outer_r, bottom*thread_size + z_incr],
                         [x_incr_outer/2, -outer_r, top*thread_size + z_incr],
                         [-x_incr_outer/2, -outer_r, top*thread_size]
                        ],
               faces = [
                         [0, 3, 7, 4],
                         [1, 5, 6, 2],
                         [0, 1, 2, 3],
                         [4, 7, 6, 5],
                         [7, 2, 6],
                         [7, 3, 2],
                         [0, 5, 1],
                         [0, 4, 5]
                        ]
            );
         } else {
            polyhedron (
               points = [
                         [-x_incr_inner/2, -inner_r, 0],
                         [x_incr_inner/2, -inner_r, z_incr],
                         [x_incr_inner/2, -inner_r, thread_size + z_incr],
                         [-x_incr_inner/2, -inner_r, thread_size],
                         [-x_incr_outer/2, -outer_r, z0_outer],
                         [x_incr_outer/2, -outer_r, z0_outer + z_incr],
                         [x_incr_outer/2, -outer_r, thread_size - z0_outer + z_incr],
                         [-x_incr_outer/2, -outer_r, thread_size - z0_outer]
                        ],
               faces = [
                         [0, 3, 7, 4],
                         [1, 5, 6, 2],
                         [0, 1, 2, 3],
                         [4, 7, 6, 5],
                         [7, 2, 6],
                         [7, 3, 2],
                         [0, 5, 1],
                         [0, 4, 5]
                        ]
            );
         }
      }
   }
}

// ----------------------------------------------------------------------------
module english_thread (diameter=0.25, threads_per_inch=20, length=1,
                      internal=false, n_starts=1, thread_size=-1, groove=false,
                      square=false, rectangle=0, angle=30, taper=0, leadin=0,
                      leadfac=1.0, test=false)
{
   mm_diameter = diameter*25.4;
   mm_pitch = (1.0/threads_per_inch)*25.4;
   mm_length = length*25.4;

   echo (str ("mm_diameter: ", mm_diameter));
   echo (str ("mm_pitch: ", mm_pitch));
   echo (str ("mm_length: ", mm_length));
   metric_thread (mm_diameter, mm_pitch, mm_length, internal, n_starts,
                  thread_size, groove, square, rectangle, angle, taper, leadin,
                  leadfac, test);
}
